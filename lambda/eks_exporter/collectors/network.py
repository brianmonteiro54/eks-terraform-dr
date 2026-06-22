"""Rede: VPC, subnets, route tables, rotas, NAT, IGW, DHCP, endpoints e
attachments de Transit Gateway da conta de ORIGEM."""
import json

from ..helpers import _tags_to_map

def collect_network(vpc_id, referenced_subnet_ids, region, profile, runner,
                    capture_full_vpc=True):
    """
    Coleta a definição da VPC e das subnets, mais o roteamento (route tables/
    rotas/associações).
    capture_full_vpc:
      - True (PADRÃO): captura a VPC INTEIRA — TODAS as subnets da VPC (públicas
        e privadas), seus route tables, IGW, flag de NAT, TGW attachments e
        gateway endpoints. Ideal para recuperação na MESMA conta com a VPC
        apagada (recria a rede completa sem precisar listar subnets na mão).
        Observação: NAT é recriado como 1 único (não 1-por-AZ); veja o .tf.
      - False (--cluster-subnets-only): captura SÓ as subnets que o cluster/
        nodegroups/fargate referenciam (bom para DR entre contas, onde a VPC do
        destino é reusada e não se quer recriar a rede inteira).
    Retorna um dict com:
      vpc:        campos para as variáveis vpc_* (cidr, tenancy, dns, tags, name)
      secondary_cidrs: list
      subnets:    {subnet_id_origem: {...}}
      route_tables, routes, route_table_associations
      create_internet_gateway, create_nat_gateways (bool, refletem a origem)
      dropped_routes: list (rotas não-portáveis, apenas documentadas)
    """
    out = {
        "vpc": {}, "secondary_cidrs": [], "subnets": {},
        "route_tables": {}, "routes": [], "route_table_associations": [],
        "create_internet_gateway": False, "create_nat_gateways": False,
        "dropped_routes": [],
        "transit_gateway_attachments": {}, "gateway_endpoints": {}, "nat_gateways": {},
        "interface_endpoints": {}, "interface_endpoint_sg_ids": [], "dhcp_options": {},
        "orphan_nat_routes": [],
    }
    # ---- VPC ----
    vpc_resp = runner(f"aws ec2 describe-vpcs --vpc-ids {vpc_id} --region {region}", profile)
    vpcs = (vpc_resp or {}).get("Vpcs", [])
    if not vpcs:
        return out
    vpc = vpcs[0]
    primary_cidr = vpc.get("CidrBlock")
    vpc_tags = _tags_to_map(vpc.get("Tags"))
    # CIDRs secundários (associados, diferentes do primário).
    secondary = []
    for assoc in vpc.get("CidrBlockAssociationSet", []):
        c = assoc.get("CidrBlock")
        state = assoc.get("CidrBlockState", {}).get("State")
        if c and c != primary_cidr and state in (None, "associated"):
            secondary.append(c)
    # Atributos DNS exigem chamadas separadas.
    dns_support = runner(
        f"aws ec2 describe-vpc-attribute --vpc-id {vpc_id} --attribute enableDnsSupport --region {region}",
        profile,
    )
    dns_hostnames = runner(
        f"aws ec2 describe-vpc-attribute --vpc-id {vpc_id} --attribute enableDnsHostnames --region {region}",
        profile,
    )
    enable_dns_support = (dns_support or {}).get("EnableDnsSupport", {}).get("Value", True)
    enable_dns_hostnames = (dns_hostnames or {}).get("EnableDnsHostnames", {}).get("Value", True)
    out["vpc"] = {
        "cidr": primary_cidr,
        "instance_tenancy": vpc.get("InstanceTenancy", "default"),
        "enable_dns_support": bool(enable_dns_support),
        "enable_dns_hostnames": bool(enable_dns_hostnames),
        "tags": vpc_tags,
        "name": vpc_tags.get("Name", "eks-vpc"),
    }
    out["secondary_cidrs"] = secondary
    # ---- DHCP options set ----
    # Recria o conjunto de opções DHCP da VPC SÓ quando é customizado (DNS on-prem,
    # NTP, NetBIOS). Se for o default (domain-name-servers = AmazonProvidedDNS e nada
    # mais), pula — a VPC nova já recebe o default da região. Sem isso, uma VPC com
    # DNS híbrido perderia a resolução de nomes corporativos no destino.
    dopt_id = vpc.get("DhcpOptionsId", "") or ""
    if dopt_id:
        dopt_resp = runner(
            f"aws ec2 describe-dhcp-options --dhcp-options-ids {dopt_id} --region {region}",
            profile,
        )
        dopts = (dopt_resp or {}).get("DhcpOptions", [])
        if dopts:
            # DhcpConfigurations: [{Key, Values:[{Value}]}] -> {key: [valores]}
            cfg = {}
            for c in dopts[0].get("DhcpConfigurations", []) or []:
                key = c.get("Key", "")
                vals = [v.get("Value") for v in (c.get("Values", []) or []) if v.get("Value") is not None]
                if key:
                    cfg[key] = vals
            dns = cfg.get("domain-name-servers", [])
            ntp = cfg.get("ntp-servers", [])
            netbios = cfg.get("netbios-name-servers", [])
            node_type = cfg.get("netbios-node-type", [])
            domain = cfg.get("domain-name", [])
            # "Customizado" = DNS diferente do AmazonProvidedDNS, ou tem NTP/NetBIOS.
            is_custom = (
                (dns and dns != ["AmazonProvidedDNS"]) or bool(ntp) or bool(netbios)
            )
            if is_custom:
                out["dhcp_options"][dopt_id] = {
                    "domain_name": domain[0] if domain else "",
                    "domain_name_servers": dns,
                    "ntp_servers": ntp,
                    "netbios_name_servers": netbios,
                    "netbios_node_type": node_type[0] if node_type else "",
                    "tags": _tags_to_map(dopts[0].get("Tags")),
                }
    # ---- Subnets ----
    # capture_full_vpc: pega TODAS as subnets da VPC (não só as do cluster), para
    # recriar a camada pública+privada inteira. Senão, só as referenciadas.
    if capture_full_vpc:
        sn_resp = runner(
            f"aws ec2 describe-subnets --filters Name=vpc-id,Values={vpc_id} --region {region}",
            profile,
        )
        subnet_objs = {s["SubnetId"]: s for s in (sn_resp or {}).get("Subnets", [])}
        ref_subnets = list(subnet_objs.keys())
        if not ref_subnets:
            return out
    else:
        ref_subnets = [s for s in dict.fromkeys(referenced_subnet_ids) if s]
        if not ref_subnets:
            return out
        ids_arg = " ".join(ref_subnets)
        sn_resp = runner(f"aws ec2 describe-subnets --subnet-ids {ids_arg} --region {region}", profile)
        subnet_objs = {s["SubnetId"]: s for s in (sn_resp or {}).get("Subnets", [])}
    # ---- Route tables (todas da VPC, p/ achar associações + main RT) ----
    rt_resp = runner(
        f"aws ec2 describe-route-tables --filters Name=vpc-id,Values={vpc_id} --region {region}",
        profile,
    )
    rts = (rt_resp or {}).get("RouteTables", [])
    rt_by_id = {rt["RouteTableId"]: rt for rt in rts}
    main_rt_id = None
    subnet_to_rt = {}
    rt_has_igw = set()
    rt_has_nat = set()
    for rt in rts:
        rid = rt["RouteTableId"]
        for assoc in rt.get("Associations", []):
            if assoc.get("Main"):
                main_rt_id = rid
            sn = assoc.get("SubnetId")
            if sn:
                subnet_to_rt[sn] = rid
        for route in rt.get("Routes", []):
            gw = route.get("GatewayId", "")
            if gw.startswith("igw-"):
                rt_has_igw.add(rid)
            if route.get("NatGatewayId"):
                rt_has_nat.add(rid)
    # RT efetiva de cada subnet referenciada (explícita ou a main).
    involved_rt_ids = set()
    for sid in ref_subnets:
        rid = subnet_to_rt.get(sid, main_rt_id)
        if rid:
            involved_rt_ids.add(rid)
    # Com a VPC inteira, captura TODAS as route tables da VPC (mesmo as sem
    # subnet associada explicitamente), para reconstruir o roteamento completo.
    if capture_full_vpc:
        involved_rt_ids = set(rt_by_id.keys())
    # Subnets -> saída (com classificação public/private).
    for sid in ref_subnets:
        s = subnet_objs.get(sid)
        if not s:
            continue
        rid = subnet_to_rt.get(sid, main_rt_id)
        is_public = rid in rt_has_igw if rid else False
        out["subnets"][sid] = {
            "cidr_block": s.get("CidrBlock"),
            "availability_zone": s.get("AvailabilityZone"),
            "map_public_ip_on_launch": bool(s.get("MapPublicIpOnLaunch", False)),
            "is_public": bool(is_public),
            "tags": _tags_to_map(s.get("Tags")),
        }
    # Route tables envolvidas -> saída.
    for rid in involved_rt_ids:
        rt = rt_by_id.get(rid, {})
        out["route_tables"][rid] = {"tags": _tags_to_map(rt.get("Tags"))}
    # Rotas — captura COMPLETA (todos os alvos e destinos).
    # Pula: rota local (implícita), rotas PROPAGADAS por VGW (Origin
    # EnableVgwRoutePropagation, vêm de BGP) e rotas de GATEWAY ENDPOINT
    # (vpce-, são recriadas pelo próprio aws_vpc_endpoint, não por aws_route).
    for rid in involved_rt_ids:
        rt = rt_by_id.get(rid, {})
        for idx, route in enumerate(rt.get("Routes", [])):
            gw = route.get("GatewayId", "") or ""
            if gw == "local":
                continue
            if route.get("Origin") == "EnableVgwRoutePropagation":
                continue
            dest_cidr = route.get("DestinationCidrBlock", "") or ""
            dest_ipv6 = route.get("DestinationIpv6CidrBlock", "") or ""
            dest_pl   = route.get("DestinationPrefixListId", "") or ""
            dest_any  = dest_cidr or dest_ipv6 or dest_pl
            if not dest_any:
                continue
            # Gateway endpoint (S3/DynamoDB): a rota é gerenciada pelo endpoint.
            if gw.startswith("vpce-"):
                out["dropped_routes"].append({
                    "route_table": rid, "destination": dest_any,
                    "reason": "rota de gateway endpoint (vpce-): recrie o aws_vpc_endpoint, que recria esta rota",
                })
                continue
            # Classifica o alvo e captura o ID (literal para alvos externos).
            target_kind, target_id = "", ""
            if gw.startswith("igw-"):
                target_kind, target_id = "igw", gw
            elif gw.startswith("eigw-") or route.get("EgressOnlyInternetGatewayId"):
                target_kind = "egress_only_igw"
                target_id = route.get("EgressOnlyInternetGatewayId", "") or gw
            elif route.get("NatGatewayId"):
                target_kind, target_id = "nat", route["NatGatewayId"]
            elif route.get("TransitGatewayId"):
                target_kind, target_id = "tgw", route["TransitGatewayId"]
            elif route.get("VpcPeeringConnectionId"):
                target_kind, target_id = "peering", route["VpcPeeringConnectionId"]
            elif route.get("CarrierGatewayId"):
                target_kind, target_id = "carrier", route["CarrierGatewayId"]
            elif route.get("CoreNetworkArn"):
                target_kind, target_id = "core_network", route["CoreNetworkArn"]
            elif gw.startswith("vgw-"):
                target_kind, target_id = "vgw", gw
            elif route.get("NetworkInterfaceId") or gw.startswith("eni-"):
                target_kind = "eni"
                target_id = route.get("NetworkInterfaceId", "") or gw
            else:
                out["dropped_routes"].append({
                    "route_table": rid, "destination": dest_any,
                    "reason": f"alvo de rota desconhecido: {gw or '(sem gateway-id)'}",
                })
                continue
            out["routes"].append({
                "key": f"{rid}|{idx}",
                "route_table_source_id": rid,
                "destination_cidr_block": dest_cidr,
                "destination_ipv6_cidr_block": dest_ipv6,
                "destination_prefix_list_id": dest_pl,
                "target_kind": target_kind,
                "target_id": target_id,
            })
    # Associações subnet -> route table (para as subnets referenciadas).
    for sid in ref_subnets:
        rid = subnet_to_rt.get(sid, main_rt_id)
        if rid and sid in out["subnets"]:
            out["route_table_associations"].append({
                "key": f"{sid}|{rid}",
                "subnet_source_id": sid,
                "route_table_source_id": rid,
            })
    # Flags refletem a origem: se havia IGW/NAT nas RTs envolvidas, recria igual.
    out["create_internet_gateway"] = len(involved_rt_ids & rt_has_igw) > 0
    out["create_nat_gateways"] = len(involved_rt_ids & rt_has_nat) > 0
    # -----------------------------------------------------------------
    # TRANSIT GATEWAY ATTACHMENTS da VPC.
    # A rota "-> tgw-xxx" só funciona se a VPC estiver anexada ao TGW. O
    # attachment morre junto com a VPC, então o recriamos. As subnets do
    # attachment precisam estar entre as capturadas (a VPC inteira é capturada
    # por padrão); as que não foram capturadas são ignoradas com aviso.
    # -----------------------------------------------------------------
    tgwa_resp = runner(
        f"aws ec2 describe-transit-gateway-vpc-attachments "
        f"--filters Name=vpc-id,Values={vpc_id} Name=state,Values=available "
        f"--region {region}",
        profile,
    )
    for att in (tgwa_resp or {}).get("TransitGatewayVpcAttachments", []):
        att_id = att.get("TransitGatewayAttachmentId", "")
        tgw_id = att.get("TransitGatewayId", "")
        if not tgw_id:
            continue
        att_subnets = att.get("SubnetIds", []) or []
        known = [s for s in att_subnets if s in out["subnets"]]
        missing = [s for s in att_subnets if s not in out["subnets"]]
        opts = att.get("Options", {}) or {}
        out["transit_gateway_attachments"][att_id or tgw_id] = {
            "transit_gateway_id": tgw_id,
            "subnet_source_ids": known,
            "missing_subnets": missing,
            "dns_support": (opts.get("DnsSupport", "enable") == "enable"),
            "ipv6_support": (opts.get("Ipv6Support", "disable") == "enable"),
            "appliance_mode_support": (opts.get("ApplianceModeSupport", "disable") == "enable"),
            "tags": _tags_to_map(att.get("Tags")),
        }
    # -----------------------------------------------------------------
    # VPC GATEWAY ENDPOINTS (S3/DynamoDB) da VPC.
    # Recriamos o aws_vpc_endpoint (tipo Gateway) associado às route tables
    # capturadas; é ELE que recria as rotas por prefix-list (por isso essas
    # rotas não viram aws_route). Endpoints do tipo Interface são ignorados
    # aqui (têm ENIs/SGs/subnets — fora deste escopo).
    # -----------------------------------------------------------------
    vpce_resp = runner(
        f"aws ec2 describe-vpc-endpoints "
        f"--filters Name=vpc-id,Values={vpc_id} "
        f"--region {region}",
        profile,
    )
    for ep in (vpce_resp or {}).get("VpcEndpoints", []):
        ep_type = ep.get("VpcEndpointType", "")
        ep_id = ep.get("VpcEndpointId", "")
        pol = ep.get("PolicyDocument", "") or ""
        if isinstance(pol, dict):
            pol = json.dumps(pol)
        if ep_type == "Gateway":
            rt_known = [r for r in (ep.get("RouteTableIds", []) or []) if r in out["route_tables"]]
            out["gateway_endpoints"][ep_id] = {
                "service_name": ep.get("ServiceName", ""),
                "route_table_source_ids": rt_known,
                "policy": pol,
                "tags": _tags_to_map(ep.get("Tags")),
            }
        elif ep_type == "Interface":
            # Endpoints Interface (ECR, STS, CloudWatch Logs, EC2, etc.) — vitais
            # numa VPC privada (o cluster puxa imagens do ECR por eles). Recriados
            # FIEL à origem: subnets + SGs mapeados, e os mesmos ip_address_type e
            # dns_options. Os SGs entram na coleta find-or-create.
            sn_known = [s for s in (ep.get("SubnetIds", []) or []) if s in out["subnets"]]
            sg_ids = [g.get("GroupId") for g in (ep.get("Groups", []) or []) if g.get("GroupId")]
            dns_opts = ep.get("DnsOptions", {}) or {}
            out["interface_endpoints"][ep_id] = {
                "service_name": ep.get("ServiceName", ""),
                "subnet_source_ids": sn_known,
                "security_group_source_ids": sg_ids,
                "private_dns_enabled": bool(ep.get("PrivateDnsEnabled", False)),
                "ip_address_type": ep.get("IpAddressType", "") or "",
                "dns_record_ip_type": dns_opts.get("DnsRecordIpType", "") or "",
                "private_dns_only_for_inbound_resolver_endpoint": bool(
                    dns_opts.get("PrivateDnsOnlyForInboundResolverEndpoint", False)),
                "policy": pol,
                "tags": _tags_to_map(ep.get("Tags")),
            }
            for g in sg_ids:
                if g not in out["interface_endpoint_sg_ids"]:
                    out["interface_endpoint_sg_ids"].append(g)
        # Outros tipos (GatewayLoadBalancer, Resource, ServiceNetwork) ignorados.
    # -----------------------------------------------------------------
    # NAT GATEWAYS da VPC — recria FIEL à origem (1 por 1). Se a origem tem
    # 1 NAT por AZ, recria 1 NAT por AZ; cada rota privada aponta para o NAT
    # correto (mapeado pelo nat-id de origem). Só NATs públicos.
    # -----------------------------------------------------------------
    nat_resp = runner(
        f"aws ec2 describe-nat-gateways "
        f"--filter Name=vpc-id,Values={vpc_id} Name=state,Values=available "
        f"--region {region}",
        profile,
    )
    for nat in (nat_resp or {}).get("NatGateways", []):
        nat_id = nat.get("NatGatewayId", "")
        if not nat_id:
            continue
        conn = nat.get("ConnectivityType", "public")
        sn = nat.get("SubnetId", "")
        # NAT REGIONAL (availability_mode=regional): é multi-AZ, NÃO fica numa
        # subnet (usa vpc_id) e, em auto mode, a AWS provisiona EIPs e expande
        # pelas AZs sozinha. A API não traz SubnetId nesse caso — detecta por
        # AvailabilityMode ou pela ausência de subnet. connectivity_type é public.
        is_regional = (nat.get("AvailabilityMode", "") == "regional") or (not sn)
        if is_regional:
            out["nat_gateways"][nat_id] = {
                "subnet_source_id": "",
                "connectivity_type": "public",
                "availability_mode": "regional",
                "tags": _tags_to_map(nat.get("Tags")),
            }
            continue
        # NAT ZONAL (1 por subnet). Só público — private zonal é caso raro/distinto
        # (sem EIP, comportamento diferente). Precisa da subnet capturada.
        if conn != "public":
            continue
        if sn not in out["subnets"]:
            continue  # subnet do NAT não capturada -> não recria fiel (use VPC inteira)
        out["nat_gateways"][nat_id] = {
            "subnet_source_id": sn,
            "connectivity_type": "public",
            "availability_mode": "zonal",
            "tags": _tags_to_map(nat.get("Tags")),
        }
    # Rotas que apontam para um NAT que NÃO foi capturado acima (NAT deletado na
    # origem -> rota virou blackhole; ou NAT zonal privado, que é ignorado). NATs
    # regionais e zonais públicos JÁ são capturados acima. No template, estas rotas
    # são PULADAS (route_target_id fica "" e routes_to_create as exclui), então as
    # subnets associadas ficariam SEM essa saída — silenciosamente. Acumula para
    # AVISAR no relatório (pode quebrar o cluster: nós sem rota default não puxam ECR).
    nat_ids_capturados = set(out["nat_gateways"].keys())
    for r in out["routes"]:
        if r.get("target_kind") == "nat" and r.get("target_id") not in nat_ids_capturados:
            out["orphan_nat_routes"].append({
                "route_table_source_id": r.get("route_table_source_id", ""),
                "destination": (r.get("destination_cidr_block")
                                or r.get("destination_ipv6_cidr_block") or ""),
                "nat_id": r.get("target_id", ""),
            })
    return out
