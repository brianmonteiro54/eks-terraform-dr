"""Helpers genéricos de tags e documentos de policy (portabilidade entre contas)."""
import json
import re
import urllib.parse

_NONPORTABLE_TAG_KEYS = {"awsApplication", "eks-importer:stack"}
_NONPORTABLE_TAG_VALUE_RE = re.compile(r"arn:aws:resource-groups:")
def _strip_nonportable_tags(tagmap):
    """
    Remove de um dict de tags as que são não-portáveis entre contas:
    a chave 'awsApplication' (AppRegistry) e qualquer tag cujo valor seja um
    ARN de resource-group da origem.
    """
    out = {}
    for k, v in (tagmap or {}).items():
        if k in _NONPORTABLE_TAG_KEYS:
            continue
        if isinstance(v, str) and _NONPORTABLE_TAG_VALUE_RE.search(v):
            continue
        out[k] = v
    return out
def _tags_to_map(tag_list):
    """
    [{'Key':k,'Value':v}] -> {k: v}. Aceita None. Remove tags não-portáveis
    (AppRegistry/awsApplication e valores com ARN de resource-group).
    """
    return _strip_nonportable_tags({t["Key"]: t.get("Value", "") for t in (tag_list or [])})
def _decode_policy_doc(doc):
    """
    Documentos de policy (trust/inline) podem vir do AWS CLI como:
      • dict já decodificado (CLI v2 com --output json), ou
      • string URL-encoded (comportamento clássico da API).
    Retorna sempre uma STRING JSON canônica (pronta para o tfvars/HCL).
    """
    if doc is None:
        return "{}"
    if isinstance(doc, dict):
        return json.dumps(doc)
    if isinstance(doc, str):
        # Pode estar URL-encoded; tenta decodificar e re-serializar.
        try:
            return json.dumps(json.loads(urllib.parse.unquote(doc)))
        except (ValueError, TypeError):
            try:
                return json.dumps(json.loads(doc))
            except (ValueError, TypeError):
                return doc
    return json.dumps(doc)
def role_name_from_arn(arn):
    """
    arn:aws:iam::123456789012:role/caminho/opcional/NomeDaRole -> 'NomeDaRole'
    O get-role usa apenas o nome amigável (sem o path).
    """
    if not arn:
        return ""
    # Tudo após 'role/' é path + nome; o nome é o último segmento.
    after = arn.split(":role/", 1)[-1]
    return after.split("/")[-1]
