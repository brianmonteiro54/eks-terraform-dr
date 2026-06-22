"""Security Groups adicionais + regras, e regras manuais do Cluster SG do EKS."""
from ..helpers import _tags_to_map

def _expand_permissions(sg_id, perms, direction, managed_set, cluster_sg_id=None):
    """
    Expande IpPermissions/IpPermissionsEgress em regras individuais
    (uma por alvo).
    Referências a OUTRO security group (UserIdGroupPairs):
      • Se aponta para o Cluster SG do EKS (cluster_sg_id) -> mantém como o
        token "__CLUSTER_SG__" (o Terraform religa ao Cluster SG do cluster
        de destino, cujo ID só existe após o cluster ser criado).
      • Se aponta para um SG do conjunto gerenciado -> mantém o sg-id de origem
        (religado via sg_id_by_source).
      • Caso contrário (ex.: SGs criados em runtime pelo Load Balancer
        Controller) -> descartada e documentada ('dropped').
    Retorna (rules_list, dropped_list).
    """
    rules = []
    dropped = []
    counter = 0
    def _base(perm):
        proto = perm.get("IpProtocol")
        from_port = perm.get("FromPort")
        to_port = perm.get("ToPort")
        # Protocolo "-1" (todo tráfego) não leva portas.
        if proto == "-1":
            from_port = None
            to_port = None
        return proto, from_port, to_port
    for perm in perms or []:
        proto, from_port, to_port = _base(perm)
        for rng in perm.get("IpRanges", []):
            rules.append({
                "key": f"{sg_id}|{direction}|{counter}",
                "sg_source_id": sg_id, "ip_protocol": proto,
                "from_port": from_port, "to_port": to_port,
                "cidr_ipv4": rng.get("CidrIp", ""), "cidr_ipv6": "",
                "prefix_list_id": "", "referenced_sg_source_id": "",
                "description": rng.get("Description", "") or "",
            })
            counter += 1
        for rng in perm.get("Ipv6Ranges", []):
            rules.append({
                "key": f"{sg_id}|{direction}|{counter}",
                "sg_source_id": sg_id, "ip_protocol": proto,
                "from_port": from_port, "to_port": to_port,
                "cidr_ipv4": "", "cidr_ipv6": rng.get("CidrIpv6", ""),
                "prefix_list_id": "", "referenced_sg_source_id": "",
                "description": rng.get("Description", "") or "",
            })
            counter += 1
        for pl in perm.get("PrefixListIds", []):
            rules.append({
                "key": f"{sg_id}|{direction}|{counter}",
                "sg_source_id": sg_id, "ip_protocol": proto,
                "from_port": from_port, "to_port": to_port,
                "cidr_ipv4": "", "cidr_ipv6": "",
                "prefix_list_id": pl.get("PrefixListId", ""),
                "referenced_sg_source_id": "",
                "description": pl.get("Description", "") or "",
            })
            counter += 1
        for pair in perm.get("UserIdGroupPairs", []):
            ref = pair.get("GroupId", "")
            if cluster_sg_id and ref == cluster_sg_id:
                # Referência ao Cluster SG do EKS: mantida via token, religada
                # no destino ao Cluster SG do cluster novo.
                ref_value = "__CLUSTER_SG__"
            elif ref in managed_set:
                ref_value = ref
            else:
                dropped.append({
                    "sg": sg_id, "direction": direction, "referenced": ref,
                    "reason": "referencia SG nao gerenciado (ex.: SG criado em runtime pelo Load Balancer Controller)",
                })
                continue
            rules.append({
                "key": f"{sg_id}|{direction}|{counter}",
                "sg_source_id": sg_id, "ip_protocol": proto,
                "from_port": from_port, "to_port": to_port,
                "cidr_ipv4": "", "cidr_ipv6": "",
                "prefix_list_id": "", "referenced_sg_source_id": ref_value,
                "description": pair.get("Description", "") or "",
            })
            counter += 1
    return rules, dropped
def collect_security_groups(sg_ids, region, profile, runner, cluster_sg_id=None):
    """
    Coleta os SGs ADICIONAIS do cluster e expande suas regras.
    O conjunto gerenciado é o próprio sg_ids. Referências ao Cluster SG do EKS
    (cluster_sg_id) são preservadas via token __CLUSTER_SG__ e religadas no
    destino; referências a SGs de runtime (LB Controller) são descartadas.
    Retorna (security_groups, ingress_rules, egress_rules, dropped).
    """
    managed_set = set(s for s in sg_ids if s)
    security_groups = {}
    ingress_rules = []
    egress_rules = []
    dropped = []
    if not managed_set:
        return security_groups, ingress_rules, egress_rules, dropped
    ids_arg = " ".join(sorted(managed_set))
    resp = runner(
        f"aws ec2 describe-security-groups --group-ids {ids_arg} --region {region}", profile
    )
    for sg in (resp or {}).get("SecurityGroups", []):
        sid = sg["GroupId"]
        security_groups[sid] = {
            "name": sg.get("GroupName", ""),
            "description": sg.get("Description", "") or "Managed by Terraform",
            "tags": _tags_to_map(sg.get("Tags")),
        }
        ing, drp1 = _expand_permissions(sid, sg.get("IpPermissions"), "ingress", managed_set, cluster_sg_id)
        egr, drp2 = _expand_permissions(sid, sg.get("IpPermissionsEgress"), "egress", managed_set, cluster_sg_id)
        ingress_rules.extend(ing)
        egress_rules.extend(egr)
        dropped.extend(drp1)
        dropped.extend(drp2)
    return security_groups, ingress_rules, egress_rules, dropped
def _is_default_cluster_sg_ingress(r):
    """Regra default que o EKS já recria sozinho no Cluster SG do destino:
    ingress all-traffic auto-referenciado (self). Re-adicioná-la daria erro
    de duplicata, então é ignorada."""
    return r.get("ip_protocol") == "-1" and r.get("referenced_sg_source_id") == "__CLUSTER_SG__"
def _is_default_cluster_sg_egress(r):
    """Egress default que o EKS recria sozinho no Cluster SG do destino e que,
    portanto, NÃO deve ser recriado (re-adicionar dá InvalidPermission.Duplicate):
      • all-traffic AUTO-REFERENCIADO (a regra 'Allows EFA traffic' do EKS); e
      • all-traffic para 0.0.0.0/0 ou ::/0 (egress padrão de qualquer SG).
    Regras de egress manuais (CIDR específico, porta específica, ou referência a
    OUTRO SG) não são default e seguem mantidas."""
    if r.get("ip_protocol") != "-1":
        return False
    if r.get("referenced_sg_source_id") == "__CLUSTER_SG__":
        return True
    if r.get("cidr_ipv4") == "0.0.0.0/0" or r.get("cidr_ipv6") == "::/0":
        return True
    return False
def collect_cluster_sg_rules(cluster_sg_id, region, profile, runner, managed_set):
    """
    Captura as regras que foram ADICIONADAS manualmente ao Cluster Security
    Group gerenciado pelo EKS (ex.: liberar uma VPC de peering, liberar o
    workers SG, abrir uma porta específica).
    As regras DEFAULT do EKS (self all-traffic no ingress; all-traffic no
    egress) são descartadas, porque o EKS as recria automaticamente no cluster
    de destino e re-adicioná-las geraria erro de duplicata.
    Referências a SGs capturados (ex.: o workers SG) são religadas via
    sg_id_by_source; referência ao próprio Cluster SG vira __CLUSTER_SG__;
    referências a SGs de runtime (LB Controller) são descartadas.
    Retorna (ingress_rules, egress_rules, dropped).
    """
    if not cluster_sg_id:
        return [], [], []
    resp = runner(
        f"aws ec2 describe-security-groups --group-ids {cluster_sg_id} --region {region}", profile
    )
    sgs = (resp or {}).get("SecurityGroups", [])
    if not sgs:
        return [], [], []
    sg = sgs[0]
    mset = set(s for s in managed_set if s)
    ing, drp1 = _expand_permissions(cluster_sg_id, sg.get("IpPermissions"), "ingress", mset, cluster_sg_id)
    egr, drp2 = _expand_permissions(cluster_sg_id, sg.get("IpPermissionsEgress"), "egress", mset, cluster_sg_id)
    # Remove as regras default do EKS (recriadas sozinhas no destino).
    ing = [r for r in ing if not _is_default_cluster_sg_ingress(r)]
    egr = [r for r in egr if not _is_default_cluster_sg_egress(r)]
    # Re-chaveia para chaves estáveis e sem colisão com os SGs adicionais.
    for i, r in enumerate(ing):
        r["key"] = f"cluster-sg|ingress|{i}"
    for i, r in enumerate(egr):
        r["key"] = f"cluster-sg|egress|{i}"
    return ing, egr, (drp1 + drp2)
