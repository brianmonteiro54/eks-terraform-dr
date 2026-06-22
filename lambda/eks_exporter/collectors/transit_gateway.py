"""Transit Gateway: configuração completa (options + route tables customizadas +
rotas estáticas) para recriação cross-account quando o TGW não existe no destino."""
from ..helpers import _tags_to_map

def collect_transit_gateways(tgw_ids, region, profile, runner):
    """
    Para cada TGW referenciado por rotas/attachment, captura a configuração
    COMPLETA da origem, para permitir recriá-lo idêntico no destino quando o
    find-or-create (RAM / Name tag) não o encontrar lá.
    Captura: Options (ASN, dns_support, vpn_ecmp_support, etc.), Name + tags, e
    as route tables CUSTOMIZADAS (não a default-association) com suas rotas
    estáticas (cidr + blackhole). Tags não-portáveis são removidas.
    Chaveado pelo tgw-id de ORIGEM (a mesma chave usada em
    transit_gateway_attachments[*].transit_gateway_id e nas rotas target_id).
    Retorna (transit_gateways_dict, warnings_list).
    """
    transit_gateways = {}
    warnings = []
    for tgw_id in dict.fromkeys([t for t in tgw_ids if t]):
        tgw_resp = runner(
            f"aws ec2 describe-transit-gateways --transit-gateway-ids {tgw_id} "
            f"--region {region}", profile)
        tgws = (tgw_resp or {}).get("TransitGateways", [])
        if not tgws:
            warnings.append(
                f"Não foi possível ler o Transit Gateway '{tgw_id}' na origem "
                f"(permissão de ec2:DescribeTransitGateways?). A rota/attachment "
                f"para ele dependerá de o TGW já existir no destino (via RAM ou "
                f"mesmo Name tag); não será possível recriá-lo do zero.")
            continue
        tgw = tgws[0]
        opts = tgw.get("Options", {}) or {}
        tgw_tags = _tags_to_map(tgw.get("Tags"))
        name = tgw_tags.get("Name", "") or tgw_id
        # Route tables customizadas (exclui a default-association) + rotas estáticas.
        route_tables = {}
        non_blackhole_static = 0
        rt_resp = runner(
            f"aws ec2 describe-transit-gateway-route-tables "
            f"--filters Name=transit-gateway-id,Values={tgw_id} "
            f"Name=default-association-route-table,Values=false "
            f"Name=state,Values=available --region {region}", profile)
        for rt in (rt_resp or {}).get("TransitGatewayRouteTables", []):
            rt_id = rt.get("TransitGatewayRouteTableId", "")
            if not rt_id:
                continue
            static_routes = []
            routes_resp = runner(
                f"aws ec2 search-transit-gateway-routes "
                f"--transit-gateway-route-table-id {rt_id} "
                f"--filters Name=type,Values=static --region {region}", profile)
            for r in (routes_resp or {}).get("Routes", []):
                if r.get("State") == "deleted":
                    continue
                cidr = r.get("DestinationCidrBlock", "")
                if not cidr:
                    continue
                is_blackhole = r.get("State") == "blackhole"
                if not is_blackhole:
                    # Rota estática que aponta para um attachment: não recriável
                    # aqui (o attachment-alvo não é resolvido). Só contabiliza.
                    non_blackhole_static += 1
                    continue
                static_routes.append({"cidr": cidr, "blackhole": True})
            route_tables[rt_id] = {
                "tags": _tags_to_map(rt.get("Tags")),
                "static_routes": static_routes,
            }
        if non_blackhole_static:
            warnings.append(
                f"TGW '{name}' ({tgw_id}): {non_blackhole_static} rota(s) estática(s) "
                f"que apontam para um attachment NÃO serão recriadas (o attachment-alvo "
                f"não é resolvido pela ferramenta). Só as rotas estáticas blackhole são "
                f"recriadas. Recrie essas rotas manualmente se o TGW for criado novo.")
        transit_gateways[tgw_id] = {
            "name": name,
            "description": tgw.get("Description", "") or "",
            "amazon_side_asn": opts.get("AmazonSideAsn", 64512),
            "auto_accept_shared_attachments": opts.get("AutoAcceptSharedAttachments", "disable"),
            "default_route_table_association": opts.get("DefaultRouteTableAssociation", "enable"),
            "default_route_table_propagation": opts.get("DefaultRouteTablePropagation", "enable"),
            "dns_support": opts.get("DnsSupport", "enable"),
            "vpn_ecmp_support": opts.get("VpnEcmpSupport", "enable"),
            "multicast_support": opts.get("MulticastSupport", "disable"),
            "tags": tgw_tags,
            "route_tables": route_tables,
        }
    return transit_gateways, warnings
