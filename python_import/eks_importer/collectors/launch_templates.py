"""Launch Templates: captura a versão default e prepara recriação no destino
(remapeia SGs, recria instance profile, remove user-data)."""
from ..helpers import _tags_to_map

def _profile_name_from_ref(iam_ref):
    """Extrai o nome do instance profile de {Name:..} ou {Arn:..}."""
    if not isinstance(iam_ref, dict):
        return ""
    name = iam_ref.get("Name")
    if name:
        return name
    arn = iam_ref.get("Arn", "") or ""
    # arn:aws:iam::acct:instance-profile/NOME
    if "/" in arn:
        return arn.split("/")[-1]
    return ""
def collect_launch_templates(referenced_lts, region, profile, runner):
    """
    Para cada launch template referenciado por nodegroups, captura a definição
    da versão default e a prepara para recriação (find-or-create) no destino.
    Estratégia de portabilidade (mesma região, outra conta):
      - copia AMI, instance type, disco, metadata, monitoring, tags;
      - REMAPEIA os security groups (devolve os sg-ids para captura);
      - RECRIA o instance profile + sua role (devolve a role para captura);
      - REMOVE o user-data (o EKS injeta o bootstrap do cluster novo). Se houver
        user-data, salva em arquivo e avisa, sem quebrar.
    Retorna (launch_templates, lt_sg_source_ids, instance_profiles,
             lt_role_arns, user_data_by_lt, warnings).
    """
    launch_templates = {}
    lt_sg_source_ids = []
    instance_profiles = {}        # nome do profile -> {source_role_arn}
    lt_role_arns = []             # roles por trás dos profiles (para captura)
    user_data_by_lt = {}          # id do LT -> user-data base64 (referência)
    warnings = []
    for lt_id, lt_name in referenced_lts.items():
        resp = runner(
            f"aws ec2 describe-launch-template-versions --launch-template-id {lt_id} "
            f"--versions '$Default' --region {region}", profile)
        versions = (resp or {}).get("LaunchTemplateVersions", [])
        if not versions:
            warnings.append(
                f"Não foi possível ler o Launch Template '{lt_name or lt_id}' "
                f"({lt_id}); o nodegroup que o usa pode falhar. Verifique permissões.")
            continue
        d = versions[0].get("LaunchTemplateData", {}) or {}
        # --- Security groups (top-level ou em network interfaces) ---
        sg_ids = list(d.get("SecurityGroupIds", []) or [])
        for ni in d.get("NetworkInterfaces", []) or []:
            sg_ids += list(ni.get("Groups", []) or [])
        sg_ids = [s for s in dict.fromkeys(sg_ids) if s]
        lt_sg_source_ids += sg_ids
        # --- Instance profile + role por trás dele ---
        profile_name = _profile_name_from_ref(d.get("IamInstanceProfile"))
        if profile_name:
            ip_resp = runner(
                f"aws iam get-instance-profile --instance-profile-name {profile_name}",
                profile)
            roles = (ip_resp or {}).get("InstanceProfile", {}).get("Roles", []) or []
            role_arn = roles[0].get("Arn") if roles else ""
            # Só recriamos o profile se ele tiver uma role (sem role é inválido p/ EC2).
            if role_arn:
                instance_profiles[profile_name] = {"source_role_arn": role_arn}
                lt_role_arns.append(role_arn)
            else:
                profile_name = ""  # não referencia profile inválido no LT
                warnings.append(
                    f"Launch Template '{lt_name}': instance profile sem role associada "
                    f"foi ignorado (não pôde ser recriado).")
        # --- Block device mappings (disco) ---
        bdms = []
        for bdm in d.get("BlockDeviceMappings", []) or []:
            ebs = bdm.get("Ebs", {}) or {}
            kms = ebs.get("KmsKeyId", "")
            if kms:
                warnings.append(
                    f"Launch Template '{lt_name}': volume usa chave KMS da origem "
                    f"(`{kms}`), que não existe no destino. A criptografia EBS foi "
                    f"deixada no padrão da conta; ajuste se precisar de chave específica.")
            bdms.append({
                "device_name": bdm.get("DeviceName", ""),
                "volume_size": ebs.get("VolumeSize"),
                "volume_type": ebs.get("VolumeType", ""),
                "iops": ebs.get("Iops"),
                "throughput": ebs.get("Throughput"),
                "encrypted": str(ebs.get("Encrypted", "")).lower() if ebs.get("Encrypted") is not None else "",
                "delete_on_termination": str(ebs.get("DeleteOnTermination", "")).lower() if ebs.get("DeleteOnTermination") is not None else "",
            })
        # --- Metadata options (IMDS) ---
        mo = d.get("MetadataOptions", {}) or {}
        metadata_options = {
            "http_endpoint": mo.get("HttpEndpoint", ""),
            "http_tokens": mo.get("HttpTokens", ""),
            "http_put_response_hop_limit": mo.get("HttpPutResponseHopLimit"),
            "instance_metadata_tags": mo.get("InstanceMetadataTags", ""),
        }
        # --- Tag specifications ---
        tag_specs = []
        for ts in d.get("TagSpecifications", []) or []:
            tag_specs.append({
                "resource_type": ts.get("ResourceType", ""),
                "tags": _tags_to_map(ts.get("Tags")),
            })
        # --- User-data: removido (EKS injeta o bootstrap do cluster novo) ---
        user_data = d.get("UserData", "")
        if user_data:
            user_data_by_lt[lt_id] = user_data
            warnings.append(
                f"Launch Template '{lt_name}' tinha user-data, que foi REMOVIDO na "
                f"recriação para que o EKS gere o bootstrap do cluster NOVO (o user-data "
                f"da origem aponta para o endpoint/CA do cluster antigo). O conteúdo "
                f"original foi salvo em 'launch-templates-userdata/'. Se ele fazia algo "
                f"além do bootstrap padrão, reaplique via DaemonSet/bootstrap customizado.")
        mon = d.get("Monitoring", {}) or {}
        launch_templates[lt_id] = {
            "name": lt_name,
            "image_id": d.get("ImageId", ""),
            "instance_type": d.get("InstanceType", ""),
            "key_name": d.get("KeyName", ""),
            "ebs_optimized": str(d.get("EbsOptimized", "")).lower() if d.get("EbsOptimized") is not None else "",
            "monitoring_enabled": bool(mon.get("Enabled", False)),
            "vpc_security_group_source_ids": sg_ids,
            "iam_instance_profile_name": profile_name,
            "block_device_mappings": bdms,
            "metadata_options": metadata_options,
            "tag_specifications": tag_specs,
        }
    # dedup
    lt_sg_source_ids = list(dict.fromkeys([s for s in lt_sg_source_ids if s]))
    return (launch_templates, lt_sg_source_ids, instance_profiles,
            lt_role_arns, user_data_by_lt, warnings)
