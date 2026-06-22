"""IAM: roles (trust/managed/inline) + policies customer-managed + saneamento
de trust policy para portabilidade entre contas."""
import json
import re

from ..helpers import _decode_policy_doc, _tags_to_map, role_name_from_arn

SERVICE_LINKED_MARKER = ":role/aws-service-role/"
# IDs únicos da IAM (AIDA*/AROA*/AIPA*...) têm 21 chars: 'A' + 20 alfanum maiúsculos.
_AWS_UNIQUE_ID_RE = re.compile(r"^A[A-Z0-9]{20}$")
# Trust do EKS Pod Identity (portável entre contas).
_POD_IDENTITY_TRUST_STATEMENT = {
    "Effect": "Allow",
    "Principal": {"Service": "pods.eks.amazonaws.com"},
    "Action": ["sts:AssumeRole", "sts:TagSession"],
}
def _sanitize_trust_policy(policy, is_pod_identity_target, source_account_id,
                           captured_role_names=None):
    """
    Torna a assume_role_policy (trust policy) PORTÁVEL para outra conta:
      - remove AWS principals que são IDs únicos órfãos (ex.: "AIDA..."), que
        surgem quando o principal original foi DELETADO — a AWS rejeita esses;
      - remove principals Federated de OIDC/SAML (o provedor pertence ao cluster
        de ORIGEM e não existe no destino — a AWS rejeita esses também);
      - para AWS principals que são ARN de role/user da conta de ORIGEM:
          • se a role SERÁ criada no destino (está em captured_role_names),
            reescreve a conta para o token __DEST_ACCOUNT__ (vira a do destino);
          • senão, DESCARTA (referenciaria algo inexistente -> a AWS rejeita);
      - ARNs/account-ids de OUTRAS contas são mantidos (cross-account é aceito);
      - account-id puro da origem vira __DEST_ACCOUNT__;
      - descarta statements que ficam sem nenhum principal válido;
      - garante a trust do Pod Identity (pods.eks.amazonaws.com) quando a role é
        alvo de pod identity OU quando a policy ficaria sem nenhum statement.
    Devolve (assume_role_policy_string_JSON, lista_de_notas).
    """
    captured_role_names = captured_role_names or set()
    notes = []
    if isinstance(policy, str):
        try:
            policy = json.loads(policy)
        except Exception:
            policy = {}
    statements = policy.get("Statement", [])
    if isinstance(statements, dict):
        statements = [statements]
    _arn_re = re.compile(r"^arn:aws:iam::(\d+):(role|user)/(.+)$")
    new_statements = []
    removed_oidc = removed_orphan = rewrote_acct = removed_missing = 0
    for st in statements:
        princ = st.get("Principal", {})
        if not isinstance(princ, dict):
            new_statements.append(st)
            continue
        new_princ = {}
        for ptype, pval in princ.items():
            vals = pval if isinstance(pval, list) else [pval]
            kept = []
            for v in vals:
                vs = str(v)
                if ptype == "AWS":
                    if _AWS_UNIQUE_ID_RE.match(vs):
                        removed_orphan += 1
                        continue  # principal deletado -> descarta
                    marn = _arn_re.match(vs)
                    if marn:
                        acct = marn.group(1)
                        if acct == source_account_id:
                            # ARN de role/user da PRÓPRIA conta de origem. Reescrever
                            # para a conta de destino criaria validação de existência
                            # da role e, como as roles são criadas em paralelo
                            # (for_each), um bug intermitente de ordem. Esses trusts
                            # são vestigiais quando a role usa Pod Identity, então são
                            # descartados (a trust de pods cobre a função).
                            removed_missing += 1
                            continue
                        else:
                            kept.append(vs)  # outra conta -> cross-account, mantém
                    elif re.match(r"^\d{12}$", vs):
                        if vs == source_account_id:
                            kept.append("__DEST_ACCOUNT__")  # account-id: sem dependência
                            rewrote_acct += 1
                        else:
                            kept.append(vs)
                    else:
                        kept.append(vs)  # "*" ou outro formato
                elif ptype == "Federated":
                    if "oidc-provider" in vs or "saml-provider" in vs:
                        removed_oidc += 1
                        continue  # provedor da origem -> não portável, descarta
                    kept.append(vs)
                else:  # Service, CanonicalUser, etc. -> portável
                    kept.append(vs)
            if kept:
                new_princ[ptype] = kept[0] if len(kept) == 1 else kept
        if new_princ:
            st = dict(st)
            st["Principal"] = new_princ
            new_statements.append(st)
    has_pods = any(
        "pods.eks.amazonaws.com" in json.dumps(s.get("Principal", {}))
        for s in new_statements
    )
    if (is_pod_identity_target or not new_statements) and not has_pods:
        new_statements.append(dict(_POD_IDENTITY_TRUST_STATEMENT))
        notes.append("trust do Pod Identity (pods.eks.amazonaws.com) garantida")
    if removed_orphan:
        notes.append(f"{removed_orphan} principal(is) órfão(s) (ID de principal deletado) removido(s)")
    if removed_oidc:
        notes.append(f"{removed_oidc} principal(is) OIDC/SAML da origem removido(s) (não portável)")
    if removed_missing:
        notes.append(f"{removed_missing} principal(is) de role inexistente no destino removido(s)")
    if rewrote_acct:
        notes.append(f"{rewrote_acct} ARN(s)/ID(s) de conta reescrito(s) origem→destino")
    sanitized = {"Version": policy.get("Version", "2012-10-17"), "Statement": new_statements}
    return json.dumps(sanitized), notes
def collect_iam_roles(role_arns, region, profile, runner):
    """
    Para cada ARN de role referenciada, coleta a definição completa:
    trust policy, managed policies, inline policies, path, tags etc.
    Chaveado pelo NOME da role (chave natural cross-account).
    Retorna (iam_roles_dict, warnings_list).
    """
    iam_roles = {}
    customer_policies = {}
    warnings = []
    seen_names = set()
    # Dedup por ARN preservando ordem.
    unique_arns = []
    for arn in role_arns:
        if arn and arn not in unique_arns:
            unique_arns.append(arn)
    for arn in unique_arns:
        if SERVICE_LINKED_MARKER in arn:
            warnings.append(
                f"Role service-linked detectada e NÃO recriada (a AWS a cria "
                f"automaticamente; o find-or-create vai reutilizá-la): {arn}"
            )
            # Mesmo assim registramos para que a tabela de tradução tenha a chave;
            # como provavelmente já existe no destino, o lookup a encontrará.
        name = role_name_from_arn(arn)
        if not name or name in seen_names:
            continue
        seen_names.add(name)
        role_resp = runner(f"aws iam get-role --role-name {name}", profile)
        if not role_resp or "Role" not in role_resp:
            warnings.append(f"Não foi possível obter a role '{name}' ({arn}); pulando.")
            continue
        role = role_resp["Role"]
        attached = runner(f"aws iam list-attached-role-policies --role-name {name}", profile)
        managed_arns = [p["PolicyArn"] for p in (attached or {}).get("AttachedPolicies", [])]
        inline_list = runner(f"aws iam list-role-policies --role-name {name}", profile)
        inline_policies = {}
        for pol_name in (inline_list or {}).get("PolicyNames", []):
            pol_resp = runner(
                f"aws iam get-role-policy --role-name {name} --policy-name {pol_name}", profile
            )
            if pol_resp and "PolicyDocument" in pol_resp:
                inline_policies[pol_name] = _decode_policy_doc(pol_resp["PolicyDocument"])
        perm_boundary = ""
        pb = role.get("PermissionsBoundary")
        if isinstance(pb, dict):
            perm_boundary = pb.get("PermissionsBoundaryArn", "") or ""
        iam_roles[name] = {
            "source_arn": arn,
            "path": role.get("Path", "/"),
            "description": role.get("Description", "") or "",
            "assume_role_policy": _decode_policy_doc(role.get("AssumeRolePolicyDocument")),
            "max_session_duration": role.get("MaxSessionDuration", 3600),
            "permissions_boundary": perm_boundary,
            "managed_policy_arns": managed_arns,
            "inline_policies": inline_policies,
            "tags": _tags_to_map(role.get("Tags")),
        }
        # Policies CUSTOMER-MANAGED: captura o documento para RECRIAR no destino
        # (find-or-create por nome). As da AWS (arn:aws:iam::aws:policy/...) são
        # globais e anexadas direto, sem recriação.
        for parn in managed_arns:
            if ":policy/" not in parn or parn.startswith("arn:aws:iam::aws:policy/"):
                continue
            pol_name = parn.split("/")[-1]
            if pol_name in customer_policies:
                continue
            pol_meta = runner(f"aws iam get-policy --policy-arn {parn}", profile)
            if not pol_meta or "Policy" not in pol_meta:
                warnings.append(
                    f"Não foi possível ler a policy customer-managed '{parn}'. "
                    f"Crie-a manualmente no destino ou rode com permissão de iam:GetPolicy."
                )
                continue
            pmeta = pol_meta["Policy"]
            ver_id = pmeta.get("DefaultVersionId")
            doc = "{}"
            if ver_id:
                ver = runner(
                    f"aws iam get-policy-version --policy-arn {parn} --version-id {ver_id}",
                    profile,
                )
                if ver and "PolicyVersion" in ver:
                    doc = _decode_policy_doc(ver["PolicyVersion"].get("Document"))
            customer_policies[pol_name] = {
                "source_arn": parn,
                "path": pmeta.get("Path", "/") or "/",
                "description": pmeta.get("Description", "") or "",
                "document": doc,
            }
        # OBS: a portabilidade da trust policy (remoção de OIDC/SAML da origem,
        # principals órfãos e roles inexistentes; reescrita de conta; garantia da
        # trust de Pod Identity) é feita automaticamente em _sanitize_trust_policy,
        # aplicada após a coleta. O que foi alterado por role é reportado no
        # CLUSTER-INFO.md (seção de saneamento de trust).
    return iam_roles, customer_policies, warnings
