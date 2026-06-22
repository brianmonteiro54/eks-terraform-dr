"""Key pairs EC2: captura a chave pública da origem para recriar o par no destino."""
from ..helpers import _tags_to_map

def collect_key_pairs(key_names, region, profile, runner):
    """
    Para cada nome de key pair EC2 referenciado (launch template ou remote_access
    de nodegroup), captura a CHAVE PÚBLICA na origem para recriar o key pair no
    destino. A AWS guarda e devolve a pública via describe-key-pairs
    --include-public-key; a chave PRIVADA (que você já baixou) continua válida
    porque é par da mesma pública — ela nunca passa pela AWS nem por este script.
    Retorna (key_pairs_dict, warnings). Key pairs sem pública recuperável são
    omitidos (o chamador remove o key_name do LT para os nós subirem sem SSH).
    """
    key_pairs = {}
    warnings = []
    for name in dict.fromkeys([n for n in key_names if n]):
        resp = runner(
            f"aws ec2 describe-key-pairs --key-names {name} "
            f"--include-public-key --region {region}", profile)
        kps = (resp or {}).get("KeyPairs", [])
        if not kps:
            warnings.append(
                f"Key pair EC2 '{name}' não encontrado na origem; o launch template "
                f"que o usa terá o key_name REMOVIDO (nós sobem sem chave SSH). Importe "
                f"o key pair no destino e ajuste o LT se precisar de acesso SSH.")
            continue
        kp = kps[0]
        pub = (kp.get("PublicKey", "") or "").strip()
        if not pub:
            warnings.append(
                f"A AWS não retornou a chave pública do key pair '{name}'. O key_name "
                f"será REMOVIDO do launch template; importe o key pair manualmente no "
                f"destino se precisar de SSH aos nós.")
            continue
        key_pairs[name] = {
            "public_key": pub,
            "key_type": kp.get("KeyType", "rsa") or "rsa",
            "tags": _tags_to_map(kp.get("Tags")),
        }
    return key_pairs, warnings
