# eks_importer

Captura um cluster **Amazon EKS** existente e gera um projeto **Terraform modular**
pronto para recriar esse cluster, na mesma conta ou em **outra conta**, usando a
estratégia **find-or-create**: para cada recurso de base, o Terraform primeiro
**procura** o equivalente na conta de destino e, se não existir, **cria** um idêntico
ao da origem.

É a ferramenta ideal para **disaster recovery**, **migração entre contas**,
**clonagem de ambientes** (prod → staging) e para trazer um cluster criado "na mão"
para dentro do Terraform sem ter que escrever tudo do zero.

---

## Índice

- [Como funciona](#como-funciona)
- [O que é capturado](#o-que-é-capturado)
- [Pré-requisitos](#pré-requisitos)
- [Instalação](#instalação)
- [Uso](#uso)
- [O que é gerado](#o-que-é-gerado)
- [Aplicando no destino](#aplicando-no-destino)
- [Modos de captura](#modos-de-captura)
- [Replicação de Transit Gateway (cross-account)](#replicação-de-transit-gateway-cross-account)
- [Find-or-create e idempotência](#find-or-create-e-idempotência)
- [Limitações conhecidas](#limitações-conhecidas)
- [Estrutura do projeto](#estrutura-do-projeto)
- [Solução de problemas (FAQ)](#solução-de-problemas-faq)

---

## Como funciona

```
┌─────────────────┐      captura       ┌──────────────────────────┐      apply        ┌─────────────────┐
│   Conta ORIGEM  │  ───────────────▶  │  Terraform modular (.tf  │  ──────────────▶  │  Conta DESTINO  │
│  (cluster EKS   │   eks_importer     │  + tfvars + aws_lookup)  │   find-or-create  │  (cluster EKS   │
│   já existente) │                    │                          │                   │   recriado)     │
└─────────────────┘                    └──────────────────────────┘                   └─────────────────┘
```

1. **Captura** — o `eks_importer` lê (somente leitura) toda a configuração do
   cluster na conta de origem via AWS CLI e a serializa em um
   `terraform.auto.tfvars.json`.
2. **Geração** — escreve um conjunto de arquivos `.tf` modulares + um helper
   `scripts/aws_lookup.py` + um relatório `CLUSTER-INFO.md`.
3. **Apply** — no destino, cada recurso de base (VPC, subnets, roles, SGs, key
   pairs, Transit Gateway…) é **procurado**; se já existir, é **reutilizado**;
   se não existir, é **criado** idêntico ao da origem. A busca acontece em tempo
   de `plan`, através de um `data.external` que chama o `aws_lookup.py`.

---

## O que é capturado

| Área | Recursos |
|------|----------|
| **Rede** | VPC, subnets, route tables, rotas, Internet Gateway, NAT Gateways, DHCP options, gateway/interface endpoints, attachments de Transit Gateway |
| **Transit Gateway** | Configuração completa (ASN, dns/vpn_ecmp/multicast support, route tables customizadas e rotas estáticas) para replicação cross-account |
| **IAM** | Roles do cluster e dos node groups (trust, managed e inline policies), policies *customer-managed*, com saneamento de trust policy para portabilidade |
| **Security Groups** | SGs adicionais + regras, e as regras manuais do *Cluster SG* gerenciado pelo EKS |
| **Compute** | Launch Templates (remapeando SGs e instance profile), Node Groups, Fargate Profiles, EKS Auto Mode |
| **Acesso** | Access Entries (ignorando as automáticas da AWS), modo de autenticação |
| **Add-ons** | EKS Add-ons e suas Pod Identity Associations |
| **Outros** | Key pairs EC2 (chave pública), Pod Identities standalone |

O detalhamento completo do que foi capturado — com avisos e limitações específicas
do seu cluster — fica no arquivo **`CLUSTER-INFO.md`** gerado a cada execução.

---

## Pré-requisitos

- **Python 3.9+**
- **AWS CLI v2** instalado e autenticado
  - Na **captura**: credenciais com permissão de leitura (`Describe*`, `Get*`,
    `List*`) em **EKS, EC2, IAM** na conta de origem.
  - No **apply**: credenciais na conta de destino com permissão para criar os
    recursos, **além de** permissão de leitura (o `aws_lookup.py` roda no `plan`).
- **Terraform** (ou OpenTofu) para aplicar o projeto gerado no destino.

---

## Instalação

O pacote roda direto do diretório, sem instalar:

```bash
# a partir do diretório que contém a pasta eks_importer/
python -m eks_importer <nome-do-cluster> [regiao] [profile]
```

Ou instale como comando do sistema:

```bash
pip install .
eks-importer <nome-do-cluster> [regiao] [profile]
```

---

## Uso

```bash
python -m eks_importer <nome-do-cluster> [regiao] [profile] [--cluster-subnets-only]
```

| Argumento | Obrigatório | Descrição |
|-----------|:-----------:|-----------|
| `<nome-do-cluster>` | sim | Nome do cluster EKS na conta de origem |
| `[regiao]` | não | Região AWS (ex.: `sa-east-1`) |
| `[profile]` | não | Profile do AWS CLI da conta de **origem** |
| `--cluster-subnets-only` | não | Captura só a rede que o cluster usa (ver [Modos de captura](#modos-de-captura)) |

**Exemplos:**

```bash
# Captura a VPC inteira (padrão), usando um profile específico
python -m eks_importer meu-cluster sa-east-1 origem-prod

# Captura só a sub-rede do cluster (ideal para DR reusando a VPC do destino)
python -m eks_importer meu-cluster sa-east-1 origem-prod --cluster-subnets-only
```

A saída vai para uma pasta **`terraform-<nome-do-cluster>/`** no diretório atual.

---

## O que é gerado

```
terraform-<cluster>/
├── main.tf                      # provider, versões, data sources base
├── variables.tf                 # todas as variáveis de entrada
├── locals.tf                    # mapas de tradução origem→destino, tags-marca
├── network.tf                   # VPC, subnets, rotas, NAT, IGW, endpoints, attachments
├── transit_gateway.tf           # find-or-create de TGW (replicação cross-account)
├── iam.tf                        # roles e policies
├── security_groups.tf           # SGs adicionais e regras do cluster SG
├── launch_templates.tf          # launch templates
├── cluster.tf                    # o aws_eks_cluster
├── nodegroups.tf                 # managed node groups
├── fargate.tf                    # fargate profiles
├── access.tf                     # access entries
├── addons.tf                     # eks add-ons + pod identity
├── pod_identity.tf               # pod identity associations standalone
├── outputs.tf                    # outputs úteis
├── terraform.auto.tfvars.json   # TODA a configuração capturada da origem
├── scripts/
│   └── aws_lookup.py             # helper do data.external (find-or-create no destino)
└── CLUSTER-INFO.md               # relatório: o que foi capturado + avisos + limitações
```

### Flags de controle no `terraform.auto.tfvars.json`

| Flag | Padrão | O que faz |
|------|:------:|-----------|
| `disable_resource_reuse` | `false` | Se `true`, **desliga** o find-or-create e força a criação de tudo (não reutiliza nada existente no destino). |
| `recreate_external_routes` | `true`* | Controla a recriação de rotas/attachments externos (Transit Gateway, peering, VGW, etc.). *Só aparece quando há alvos externos. |

---

## Aplicando no destino

```bash
cd terraform-<cluster>/

# Ajuste, se necessário, aws_profile e region no terraform.auto.tfvars.json
# (apontando para a conta de DESTINO)

terraform init
terraform plan      # revise o que será reutilizado vs. criado
terraform apply
```

> **Dica:** rode `terraform plan` e leia com atenção. Recursos que o find-or-create
> **encontrou** no destino aparecem como `data` (reutilizados); o que **não** existe
> aparece como `resource` a ser criado.

---

## Modos de captura

| Modo | Flag | Quando usar |
|------|------|-------------|
| **VPC inteira** (padrão) | *(nenhuma)* | Recuperar/clonar a **rede inteira** na mesma conta. Captura todas as subnets, route tables, IGW, NAT, TGW attachments e endpoints. |
| **Só do cluster** | `--cluster-subnets-only` | **DR em outra conta** reutilizando a VPC que já existe no destino. Captura apenas a rede que o cluster efetivamente usa. |

---

## Replicação de Transit Gateway (cross-account)

Com `recreate_external_routes = true`, as rotas `-> tgw-xxx` e o attachment da VPC
funcionam em **qualquer conta**. Para cada TGW referenciado, o lookup resolve o ID
no destino em **cascata**:

1. **Mesmo ID via AWS RAM** — se o TGW da origem está compartilhado com a conta de
   destino, é usado diretamente.
2. **Mesmo `Name` tag** — procura um TGW com o mesmo nome, *owned* pela conta de
   destino, e usa o ID existente.
3. **Não encontrado** — o Terraform **cria um TGW novo** com a mesma configuração
   da origem (ASN, dns_support, vpn_ecmp_support, route tables customizadas e
   rotas estáticas *blackhole*).

O ID efetivo (encontrado ou criado) é usado pelo attachment e pelas rotas
automaticamente.

---

## Find-or-create e idempotência

O coração da portabilidade é o helper **`scripts/aws_lookup.py`**, chamado pelo
Terraform como um `data.external` durante o `plan`. Ele recebe o tipo de recurso e
os dados da origem, procura o equivalente na conta de destino e devolve o ID
encontrado (ou vazio, sinalizando que o Terraform deve criar).

Para ser **idempotente**, todo recurso que a stack cria recebe a tag-marca
`eks-importer:stack = <nome-do-cluster>`. O lookup **ignora** recursos que carregam
essa marca — assim, um segundo `terraform apply` não "reencontra" e destrói o que a
própria stack criou na primeira vez.

Quer desligar a reutilização e criar tudo do zero? Defina
`disable_resource_reuse = true` no tfvars.

---

## Limitações conhecidas

O `CLUSTER-INFO.md` lista as limitações específicas do seu cluster. As principais:

- **Cluster Security Group**: o SG criado automaticamente pelo EKS é gerenciado
  pela AWS e **não** pode ser especificado no Terraform — apenas suas regras
  manuais são recriadas.
- **Transit Gateway criado novo**: usa a *default route table* do TGW (cobre o
  caso de uma única VPC). **Associações/propagações** customizadas de route table
  e **outros attachments** (VPN, Direct Connect, outras VPCs) **não** são
  recriados automaticamente.
- **Rotas estáticas de TGW**: apenas as *blackhole* são recriadas; rotas que
  apontam para um attachment dependem de um alvo que a ferramenta não resolve.
- **VPC Peering cross-account**: continua **manual** (exige aceitação do outro
  lado da conexão).
- **User-data de Launch Templates**: removido na captura (pode conter segredos);
  reinsira se necessário.

---

## Estrutura do projeto

```
.
├── eks_importer/                # o pacote Python
│   ├── __init__.py              # API pública: generate_modular_eks_terraform
│   ├── __main__.py              # CLI: python -m eks_importer ...
│   ├── aws_cli.py               # execução do AWS CLI + registro de falhas
│   ├── helpers.py               # tags portáveis, decode de policy
│   ├── access_entries.py        # filtros de access entries automáticos
│   ├── generator.py             # orquestrador: captura + transformação
│   ├── report.py                # geração do CLUSTER-INFO.md
│   ├── collectors/              # leitores find-or-create da conta de ORIGEM
│   │   ├── iam.py
│   │   ├── network.py
│   │   ├── transit_gateway.py
│   │   ├── security_groups.py
│   │   ├── launch_templates.py
│   │   └── key_pairs.py
│   ├── terraform/
│   │   ├── __init__.py          # TERRAFORM_FILES (nome → conteúdo)
│   │   └── templates.py         # todos os templates HCL (.tf)
│   └── lookup/
│       └── aws_lookup.py        # helper do data.external
├── run_eks_importer.py          # lançador equivalente a `python -m eks_importer`
├── pyproject.toml               # empacotamento (pip install .)
└── README.md
```

---

## Solução de problemas (FAQ)

**Para que serve a pasta `__pycache__`?**
É o cache de **bytecode** do Python. No primeiro `import`, cada módulo `.py` é
compilado para um `.pyc` e guardado ali para acelerar as execuções seguintes. É
seguro deletar (o Python recria sozinho ao importar) e não afeta o Terraform
gerado. Já está no `.gitignore`. Para não criar o cache, rode com
`python -B -m eks_importer ...`.

**`terraform plan` falha com `InvalidTransitGatewayID.NotFound` (ou similar).**
Garanta que `recreate_external_routes = true` no tfvars e que as credenciais do
destino têm permissão de leitura (o `aws_lookup.py` roda no `plan`).

**A captura terminou com avisos de "Comandos AWS que falharam".**
Normalmente é permissão IAM faltando na conta de origem. O `CLUSTER-INFO.md` lista
exatamente quais chamadas falharam — conceda as permissões `Describe*/Get*/List*`
correspondentes e rode de novo.

**Quero criar tudo do zero, sem reutilizar nada do destino.**
Defina `disable_resource_reuse = true` no `terraform.auto.tfvars.json`.

**O attachment do TGW ficou incompleto (subnets faltando).**
Capture a VPC inteira (modo padrão, sem `--cluster-subnets-only`) para que todas
as subnets do attachment sejam capturadas.