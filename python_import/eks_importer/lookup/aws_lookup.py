#!/usr/bin/env python3
"""
aws_lookup.py — Helper para o `external` data source do Terraform.

Este script é o coração da estratégia "find-or-create": ele consulta a conta
AWS de DESTINO (a conta onde o `terraform apply` está rodando) e responde
"esse recurso já existe? se sim, qual o ID/ARN dele?".

Por que um script em vez do data source nativo `aws_vpcs`/`aws_iam_roles`?
  A documentação oficial do `aws_vpcs` diz textualmente:
  "This data source will fail if none are found."
  Ou seja, o data source nativo QUEBRA o apply quando não encontra nada — que é
  justamente o caso "conta nova, ainda não tem a VPC". Já o AWS CLI retorna uma
  lista vazia (`{"Vpcs": []}`) sem erro. Por isso usamos o `external` data source
  apoiado neste script: ele SEMPRE termina com sucesso, devolvendo o ID
  encontrado ou uma string vazia.

Protocolo do `external` data source (hashicorp/external):
  - Lê um objeto JSON do stdin (os argumentos de `query`, todos strings).
  - Escreve no stdout um objeto JSON cujos valores também são TODOS strings.
  - Sai com status 0 em sucesso; status != 0 + mensagem no stderr em erro real.
  (Ref.: registry.terraform.io/providers/hashicorp/external/latest/docs/data-sources/external)

Entrada (stdin), exemplos:
  {"kind": "vpc",            "region": "sa-east-1", "cidr": "10.0.0.0/16"}
  {"kind": "subnet",         "region": "sa-east-1", "vpc_id": "vpc-123", "cidr": "10.0.1.0/24"}
  {"kind": "security_group", "region": "sa-east-1", "vpc_id": "vpc-123", "name": "eks-extra-sg"}
  {"kind": "internet_gateway","region":"sa-east-1", "vpc_id": "vpc-123"}
  {"kind": "iam_role",       "name": "eksServiceRole"}
  {"kind": "iam_policy",     "name": "minha-policy-custom"}
  (campo opcional "profile" em qualquer um deles)

Saída (stdout):
  {"id": "vpc-0abc..."}   ou {"id": ""}    para recursos com ID
  {"arn": "arn:aws:..."}  ou {"arn": ""}   para IAM role/policy
"""
import ipaddress
import json
import subprocess
import sys


def _eprint(*args):
    print(*args, file=sys.stderr)


def _run_cli(args, profile=None, region=None):
    """Executa o AWS CLI e devolve (json_decodificado, stderr_str).

    Levanta RuntimeError APENAS para falhas que não sejam "recurso inexistente".
    """
    cmd = ["aws"] + args + ["--output", "json"]
    if region:
        cmd += ["--region", region]
    if profile:
        cmd += ["--profile", profile]

    try:
        # O 'external' data source NÃO tem timeout próprio: se o AWS CLI travar
        # (rede/credencial), o Terraform ficaria pendurado para sempre. Limitamos.
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except FileNotFoundError:
        raise RuntimeError(
            "AWS CLI nao encontrado no PATH. O 'terraform apply' desta stack "
            "precisa do AWS CLI instalado e autenticado na conta de destino."
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(
            f"AWS CLI excedeu 60s em: {' '.join(args[:3])} ... "
            "Verifique conectividade e credenciais da conta de DESTINO "
            "(o lookup precisa responder rapido para o terraform nao travar)."
        )

    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        # "Não encontrado" não é erro fatal para nós — quem trata é o chamador.
        return None, stderr

    out = (proc.stdout or "").strip()
    if not out:
        return None, ""
    try:
        return json.loads(out), ""
    except json.JSONDecodeError:
        raise RuntimeError(f"Saida do AWS CLI nao e JSON valido: {out[:200]}")


# "Recurso inexistente" no IAM aparece como NoSuchEntity / cannot be found.
_NOT_FOUND_MARKERS = ("NoSuchEntity", "cannot be found", "does not exist", "NoSuchEntityException")

# Tag-marca que esta ferramenta coloca em TODO recurso que ela mesma cria.
# Os lookups EXCLUEM recursos com essa marca == a stack atual: assim, um recurso
# criado por esta stack nunca é "reencontrado" (continua gerenciado pelo state),
# e só recursos pré-existentes (sem a marca, ou de outra stack) são reaproveitados.
# É isso que torna o find-or-create idempotente automaticamente, sem flags.
_STACK_TAG_KEY = "eks-importer:stack"


def _tags_to_dict(tags):
    """[{'Key':k,'Value':v}, ...] -> {k: v}. Aceita None."""
    out = {}
    for t in (tags or []):
        k = t.get("Key")
        if k is not None:
            out[k] = t.get("Value", "")
    return out


def _is_ours(tags, p):
    """True se o recurso tem a tag-marca desta stack -> deve ser IGNORADO no
    lookup (é nosso, já está no state). 'exclude_value' vem do nome do cluster.
    Vazio/ausente => nunca exclui (retrocompatível com .tf antigo)."""
    val = p.get("exclude_value", "") or ""
    if not val:
        return False
    return _tags_to_dict(tags).get(_STACK_TAG_KEY, "") == val


def lookup_vpc(p):
    data, err = _run_cli(
        ["ec2", "describe-vpcs", "--filters", f"Name=cidr,Values={p['cidr']}"],
        profile=p.get("profile"), region=p.get("region"),
    )
    if data is None and err:
        raise RuntimeError(err)
    for v in (data or {}).get("Vpcs", []):
        if not _is_ours(v.get("Tags"), p):   # pula a que esta stack criou
            return {"id": v["VpcId"]}
    return {"id": ""}


def lookup_subnet(p):
    data, err = _run_cli(
        ["ec2", "describe-subnets", "--filters",
         f"Name=vpc-id,Values={p['vpc_id']}", f"Name=cidr-block,Values={p['cidr']}"],
        profile=p.get("profile"), region=p.get("region"),
    )
    if data is None and err:
        raise RuntimeError(err)
    for s in (data or {}).get("Subnets", []):
        if not _is_ours(s.get("Tags"), p):
            return {"id": s["SubnetId"]}
    return {"id": ""}


def lookup_security_group(p):
    data, err = _run_cli(
        ["ec2", "describe-security-groups", "--filters",
         f"Name=vpc-id,Values={p['vpc_id']}", f"Name=group-name,Values={p['name']}"],
        profile=p.get("profile"), region=p.get("region"),
    )
    if data is None and err:
        raise RuntimeError(err)
    for sg in (data or {}).get("SecurityGroups", []):
        if not _is_ours(sg.get("Tags"), p):
            return {"id": sg["GroupId"]}
    return {"id": ""}


def lookup_internet_gateway(p):
    data, err = _run_cli(
        ["ec2", "describe-internet-gateways", "--filters",
         f"Name=attachment.vpc-id,Values={p['vpc_id']}"],
        profile=p.get("profile"), region=p.get("region"),
    )
    if data is None and err:
        raise RuntimeError(err)
    for igw in (data or {}).get("InternetGateways", []):
        if not _is_ours(igw.get("Tags"), p):
            return {"id": igw["InternetGatewayId"]}
    return {"id": ""}


def lookup_iam_role(p):
    # IAM é global: get-role devolve NoSuchEntity quando não existe.
    data, err = _run_cli(["iam", "get-role", "--role-name", p["name"]],
                         profile=p.get("profile"))
    if data is None:
        if err and any(m in err for m in _NOT_FOUND_MARKERS):
            return {"arn": ""}          # não existe -> criar
        if err:
            raise RuntimeError(err)     # erro real (ex.: AccessDenied)
        return {"arn": ""}
    role = data.get("Role", {})
    if _is_ours(role.get("Tags"), p):   # nossa -> trata como "criar/gerenciar"
        return {"arn": ""}
    return {"arn": role.get("Arn", "")}


def lookup_iam_policy(p):
    # Procura uma policy gerenciada pelo cliente pelo nome (escopo Local).
    data, err = _run_cli(
        ["iam", "list-policies", "--scope", "Local", "--max-items", "1000"],
        profile=p.get("profile"),
    )
    if data is None and err:
        raise RuntimeError(err)
    for pol in (data or {}).get("Policies", []):
        if pol.get("PolicyName") == p["name"]:
            arn = pol.get("Arn", "")
            # list-policies não traz Tags; busca à parte para checar a marca.
            if p.get("exclude_value"):
                tdata, _terr = _run_cli(
                    ["iam", "list-policy-tags", "--policy-arn", arn],
                    profile=p.get("profile"),
                )
                if tdata is not None and _is_ours(tdata.get("Tags"), p):
                    return {"arn": ""}   # nossa -> criar/gerenciar
            return {"arn": arn}
    return {"arn": ""}


def lookup_launch_template(p):
    # Procura um launch template pelo NOME. Devolve id + versao default.
    data, err = _run_cli(
        ["ec2", "describe-launch-templates", "--filters",
         f"Name=launch-template-name,Values={p['name']}"],
        profile=p.get("profile"), region=p.get("region"),
    )
    if data is None:
        # describe-launch-templates erra se não encontra nada; tratamos como vazio.
        if err and any(m in err for m in ("NotFound", "does not exist", "InvalidLaunchTemplate")):
            return {"id": "", "default_version": ""}
        if err:
            raise RuntimeError(err)
        return {"id": "", "default_version": ""}
    lts = (data or {}).get("LaunchTemplates", [])
    for lt in lts:
        if not _is_ours(lt.get("Tags"), p):
            return {
                "id": lt.get("LaunchTemplateId", ""),
                "default_version": lt.get("DefaultVersionNumber", ""),
            }
    return {"id": "", "default_version": ""}


def lookup_instance_profile(p):
    # IAM global: get-instance-profile devolve NoSuchEntity quando não existe.
    data, err = _run_cli(
        ["iam", "get-instance-profile", "--instance-profile-name", p["name"]],
        profile=p.get("profile"),
    )
    if data is None:
        if err and any(m in err for m in _NOT_FOUND_MARKERS):
            return {"name": ""}          # não existe -> criar
        if err:
            raise RuntimeError(err)
        return {"name": ""}
    ip = data.get("InstanceProfile", {})
    if _is_ours(ip.get("Tags"), p):
        return {"name": ""}
    return {"name": ip.get("InstanceProfileName", "")}


def lookup_iam_user(p):
    # IAM global: get-user devolve NoSuchEntity quando não existe.
    data, err = _run_cli(["iam", "get-user", "--user-name", p["name"]],
                         profile=p.get("profile"))
    if data is None:
        if err and any(m in err for m in _NOT_FOUND_MARKERS):
            return {"arn": ""}          # não existe -> criar
        if err:
            raise RuntimeError(err)
        return {"arn": ""}
    user = data.get("User", {})
    if _is_ours(user.get("Tags"), p):
        return {"arn": ""}
    return {"arn": user.get("Arn", "")}


def lookup_key_pair(p):
    # Key pair EC2 é regional. describe-key-pairs erra (InvalidKeyPair.NotFound)
    # quando não existe; tratamos como vazio -> criar.
    data, err = _run_cli(
        ["ec2", "describe-key-pairs", "--key-names", p["name"]],
        profile=p.get("profile"), region=p.get("region"),
    )
    if data is None:
        if err and any(m in err for m in ("NotFound", "does not exist", "InvalidKeyPair")):
            return {"name": ""}
        if err:
            raise RuntimeError(err)
        return {"name": ""}
    kps = (data or {}).get("KeyPairs", [])
    for kp in kps:
        if not _is_ours(kp.get("Tags"), p):
            return {"name": kp.get("KeyName", "")}
    return {"name": ""}


def _account_id(profile=None):
    """Account-id da conta de DESTINO (via STS). Usado para restringir a busca
    por Name tag ao owner correto. Falha silenciosa -> string vazia."""
    data, _err = _run_cli(["sts", "get-caller-identity"], profile=profile)
    if data:
        return data.get("Account", "") or ""
    return ""


def lookup_transit_gateway(p):
    """
    Find-or-create de Transit Gateway (portabilidade cross-account):
      1) MESMO ID visivel no destino (compartilhado via AWS RAM) -> usa direto;
      2) MESMO Name tag, owned pela conta de destino -> usa o ID novo;
      3) Nao encontrado -> devolve found=false (o Terraform cria um TGW novo).
    Ignora TGWs com a tag-marca desta stack (idempotencia: nao "reencontra" o
    TGW que esta propria stack criou, evitando que o apply seguinte o destrua).
    Saida: {"id": "...", "found": "true|false", "method": "..."}
    """
    source_id = p.get("source_tgw_id", "") or ""
    name = p.get("tgw_name", "") or ""
    region = p.get("region")
    profile = p.get("profile")
    # --- Estrategia 1: mesmo ID (RAM compartilhado ou mesma conta) ---
    if source_id:
        data, _err = _run_cli(
            ["ec2", "describe-transit-gateways", "--transit-gateway-ids", source_id],
            profile=profile, region=region,
        )
        # data is None quando o ID nao existe (InvalidTransitGatewayID.NotFound)
        # -> segue para a estrategia 2 sem erro.
        for tgw in (data or {}).get("TransitGateways", []):
            if tgw.get("State") not in ("available", "modifying", "pending"):
                continue
            if _is_ours(tgw.get("Tags"), p):
                return {"id": "", "found": "false", "method": "ours"}
            return {"id": tgw.get("TransitGatewayId", ""), "found": "true", "method": "ram_shared"}
    # --- Estrategia 2: por Name tag, restrito ao owner do destino ---
    if name:
        filters = [f"Name=tag:Name,Values={name}", "Name=state,Values=available"]
        acct = _account_id(profile)
        if acct:
            filters.append(f"Name=owner-id,Values={acct}")
        data, err = _run_cli(
            ["ec2", "describe-transit-gateways", "--filters"] + filters,
            profile=profile, region=region,
        )
        if data is None and err:
            raise RuntimeError(err)
        for tgw in (data or {}).get("TransitGateways", []):
            if _is_ours(tgw.get("Tags"), p):
                continue  # pula o TGW que esta stack criou
            return {"id": tgw.get("TransitGatewayId", ""), "found": "true", "method": "by_name"}
    # --- Estrategia 3: nao encontrado -> Terraform cria ---
    return {"id": "", "found": "false", "method": "not_found"}


def lookup_vpn_gateway(p):
    """
    Find-or-skip de VPN Gateway (VGW). Uma VPC tem no maximo UM VGW anexado,
    entao procura o VGW attached a VPC do destino. Achou -> usa o ID; nao achou
    -> devolve "" (o network.tf PULA a rota, sem derrubar o apply). Nao cria o
    VGW: a conectividade real (customer gateways, tuneis, PSK, BGP) tem segredo e
    nao e capturavel. Ignora VGWs com a tag-marca desta stack.
    Saida: {"id": "..."} ou {"id": ""}.
    """
    vpc = p.get("vpc_id", "") or ""
    if not vpc:
        return {"id": ""}
    data, err = _run_cli(
        ["ec2", "describe-vpn-gateways", "--filters",
         f"Name=attachment.vpc-id,Values={vpc}", "Name=attachment.state,Values=attached"],
        profile=p.get("profile"), region=p.get("region"),
    )
    if data is None and err:
        raise RuntimeError(err)
    for vgw in (data or {}).get("VpnGateways", []):
        if _is_ours(vgw.get("Tags"), p):
            continue
        for att in vgw.get("VpcAttachments", []) or []:
            if att.get("VpcId") == vpc and att.get("State") == "attached":
                return {"id": vgw.get("VpnGatewayId", "")}
    return {"id": ""}


def lookup_peering(p):
    """
    Find-or-skip de VPC peering. Procura uma conexao de peering ATIVA que envolva
    a VPC do destino e cujo OUTRO lado cubra o CIDR de destino da rota. Achou ->
    usa o ID; nao achou -> devolve "" (o network.tf PULA a rota). Nao cria peering:
    cross-account exige aceitacao na outra conta (credencial do peer). Ignora as
    conexoes com a tag-marca desta stack.
    Saida: {"id": "..."} ou {"id": ""}.
    """
    vpc = p.get("vpc_id", "") or ""
    peer_cidr = p.get("peer_cidr", "") or ""
    if not vpc:
        return {"id": ""}
    data, err = _run_cli(
        ["ec2", "describe-vpc-peering-connections", "--filters",
         "Name=status-code,Values=active"],
        profile=p.get("profile"), region=p.get("region"),
    )
    if data is None and err:
        raise RuntimeError(err)
    for pcx in (data or {}).get("VpcPeeringConnections", []):
        if _is_ours(pcx.get("Tags"), p):
            continue
        acc = pcx.get("AccepterVpcInfo", {}) or {}
        req = pcx.get("RequesterVpcInfo", {}) or {}
        # uma ponta precisa ser a nossa VPC; a OUTRA e quem deve cobrir o CIDR.
        if req.get("VpcId") == vpc:
            other = acc
        elif acc.get("VpcId") == vpc:
            other = req
        else:
            continue
        if not peer_cidr:
            return {"id": pcx.get("VpcPeeringConnectionId", "")}
        cidrs = [c.get("CidrBlock") for c in (other.get("CidrBlockSet", []) or [])]
        if other.get("CidrBlock"):
            cidrs.append(other.get("CidrBlock"))
        if _cidr_overlaps(peer_cidr, cidrs):
            return {"id": pcx.get("VpcPeeringConnectionId", "")}
    return {"id": ""}


def _cidr_overlaps(needle, cidrs):
    """True se a rede `needle` sobrepõe (igual, contém ou está contida em) alguma
    das redes em `cidrs`. Mais robusto que igualdade de string: uma rota costuma
    ser mais específica que o CIDR do peering (ex.: rota 10.50.1.0/24 para um
    peering que cobre 10.50.0.0/16). CIDR inválido é ignorado."""
    try:
        n = ipaddress.ip_network(needle, strict=False)
    except ValueError:
        return False
    for c in cidrs:
        if not c:
            continue
        try:
            h = ipaddress.ip_network(c, strict=False)
        except ValueError:
            continue
        if n.version == h.version and n.overlaps(h):
            return True
    return False


def lookup_carrier_gateway(p):
    """
    Find-or-skip de carrier gateway (Wavelength). É por-VPC e morre com a VPC, então
    o ID literal da origem nunca vale numa VPC nova/outra conta. Procura o carrier
    gateway da VPC no DESTINO; achou -> usa; não achou -> "" (rota pulada, sem falhar
    o apply). Ignora os com a tag-marca desta stack.
    """
    vpc = p.get("vpc_id", "") or ""
    if not vpc:
        return {"id": ""}
    data, err = _run_cli(
        ["ec2", "describe-carrier-gateways", "--filters",
         f"Name=vpc-id,Values={vpc}", "Name=state,Values=available"],
        profile=p.get("profile"), region=p.get("region"),
    )
    if data is None and err:
        raise RuntimeError(err)
    for cg in (data or {}).get("CarrierGateways", []):
        if _is_ours(cg.get("Tags"), p):
            continue
        return {"id": cg.get("CarrierGatewayId", "")}
    return {"id": ""}


_HANDLERS = {
    "vpc": lookup_vpc,
    "subnet": lookup_subnet,
    "security_group": lookup_security_group,
    "internet_gateway": lookup_internet_gateway,
    "iam_role": lookup_iam_role,
    "iam_policy": lookup_iam_policy,
    "iam_user": lookup_iam_user,
    "key_pair": lookup_key_pair,
    "launch_template": lookup_launch_template,
    "instance_profile": lookup_instance_profile,
    "transit_gateway": lookup_transit_gateway,
    "vpn_gateway": lookup_vpn_gateway,
    "peering": lookup_peering,
    "carrier_gateway": lookup_carrier_gateway,
}


def main():
    try:
        raw = sys.stdin.read()
        params = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError as e:
        _eprint(f"Entrada invalida (esperado JSON no stdin): {e}")
        sys.exit(1)

    kind = params.get("kind")
    handler = _HANDLERS.get(kind)
    if handler is None:
        _eprint(f"kind desconhecido: {kind!r}. Validos: {', '.join(_HANDLERS)}")
        sys.exit(1)

    try:
        result = handler(params)
    except KeyError as e:
        _eprint(f"Parametro obrigatorio ausente para kind={kind}: {e}")
        sys.exit(1)
    except RuntimeError as e:
        _eprint(f"Falha ao consultar AWS ({kind}): {e}")
        sys.exit(1)

    # Garantia do protocolo: todos os valores precisam ser strings.
    result = {k: ("" if v is None else str(v)) for k, v in result.items()}
    sys.stdout.write(json.dumps(result))


if __name__ == "__main__":
    main()
