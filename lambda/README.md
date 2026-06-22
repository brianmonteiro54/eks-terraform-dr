# eks_exporter (Lambda)

Versão **AWS Lambda** do exportador de EKS → Terraform modular (find-or-create,
portável entre contas). Captura o cluster na conta de **origem** via **boto3** e faz
**push** dos arquivos gerados para um repositório **GitLab** (com retentativa para
concorrência entre Lambdas no mesmo branch).

Esta versão está **modularizada** (igual ao pacote CLI) e já inclui a **replicação de
Transit Gateway cross-account** e o **reposicionamento de `recreate_external_routes`**
no `terraform.auto.tfvars.json`.

## Estrutura

```
lambda_function.py            # shim: handler = lambda_function.lambda_handler
eks_exporter/
├── __init__.py
├── handler.py                # lambda_handler (orquestra geração + push GitLab)
├── config.py                 # get_config + resolução do GITLAB_TOKEN (Secrets Manager)
├── aws_boto3.py              # run_aws_command: traduz "aws ..." -> chamada boto3
├── gitlab_api.py             # GitLabAPI (commit com retry + jitter)
├── generator.py              # generate_terraform_files: gera tudo EM MEMÓRIA (dict)
├── report.py                 # render_cluster_info -> string do CLUSTER-INFO.md
├── helpers.py                # tags portáveis, decode de policy        (idêntico ao CLI)
├── access_entries.py         # filtros de access entries automáticos    (idêntico ao CLI)
├── collectors/               # leitores find-or-create da ORIGEM        (idêntico ao CLI)
│   ├── iam.py  network.py  transit_gateway.py
│   ├── security_groups.py  launch_templates.py  key_pairs.py
├── terraform/                # templates HCL + TERRAFORM_FILES          (idêntico ao CLI)
│   ├── __init__.py  templates.py
└── lookup/
    └── aws_lookup.py         # helper do data.external (find-or-create no destino)
```

Os módulos marcados "idêntico ao CLI" são os mesmos do importer de linha de comando —
a lógica de coleta/transformação/relatório é compartilhada; só mudam a **borda de
I/O** (memória + GitLab, em vez de disco) e o **runner** (boto3, em vez de AWS CLI).

## Deploy

A Lambda usa apenas a biblioteca padrão + **boto3** (já provido pelo runtime Lambda),
então **não precisa empacotar dependências**.

```bash
# zip com o shim na RAIZ + o pacote
zip -r eks_exporter_lambda.zip lambda_function.py eks_exporter/
```

Configure a função:
- **Handler:** `lambda_function.lambda_handler`
- **Runtime:** Python 3.11+ (compatível com 3.9+)
- **Timeout/memória:** suficientes para a coleta (ex.: 120s / 512 MB).

## Variáveis de ambiente

| Variável | Obrigatória | Descrição |
|----------|:-----------:|-----------|
| `EKS_CLUSTER_NAME` | sim* | Nome do cluster (ou `event.cluster_name`) |
| `AWS_REGION_EKS` | sim* | Região do cluster (ou `event.region`) |
| `GITLAB_REPO` | sim | Caminho do projeto (ex.: `grupo/infra-eks`) |
| `GITLAB_BRANCH` | sim | Branch de destino do commit |
| `GITLAB_TOKEN` | sim | Token, **ou** ARN de secret no Secrets Manager (resolve `GITLAB_TOKEN` do JSON) |
| `GITLAB_URL` | não | Default `https://git.xxxx.com.br` |
| `CAPTURE_FULL_VPC` | não | `true` (padrão) captura a VPC inteira; `false` só a rede do cluster |
| `GITLAB_PUSH_MAX_RETRIES` / `..._BASE_DELAY` / `..._MAX_DELAY` | não | Retentativa do push (default 5 / 1.0 / 20.0) |

\* O `event` tem precedência sobre as variáveis de ambiente.

## Permissões (IAM da role da Lambda)

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "EKSReadOnly",
            "Effect": "Allow",
            "Action": [
                "eks:DescribeCluster",
                "eks:ListNodegroups",
                "eks:DescribeNodegroup",
                "eks:ListFargateProfiles",
                "eks:DescribeFargateProfile",
                "eks:ListAddons",
                "eks:DescribeAddon",
                "eks:ListAccessEntries",
                "eks:DescribeAccessEntry",
                "eks:ListAssociatedAccessPolicies",
                "eks:ListPodIdentityAssociations",
                "eks:DescribePodIdentityAssociation"
            ],
            "Resource": "*"
        },
        {
            "Sid": "EC2ReadOnlyForPortability",
            "Effect": "Allow",
            "Action": [
                "ec2:DescribeVpcs",
                "ec2:DescribeVpcAttribute",
                "ec2:DescribeSubnets",
                "ec2:DescribeRouteTables",
                "ec2:DescribeTransitGatewayVpcAttachments",
                "ec2:DescribeVpcEndpoints",
                "ec2:DescribeNatGateways",
                "ec2:DescribeDhcpOptions",
                "ec2:DescribeSecurityGroups",
                "ec2:DescribeLaunchTemplateVersions",
                "ec2:DescribeKeyPairs",
                "ec2:DescribeTransitGateways",
                "ec2:DescribeTransitGatewayRouteTables",
                "ec2:SearchTransitGatewayRoutes"
            ],
            "Resource": "*"
        },
        {
            "Sid": "IAMReadOnlyForRolesAndPolicies",
            "Effect": "Allow",
            "Action": [
                "iam:GetRole",
                "iam:ListAttachedRolePolicies",
                "iam:ListRolePolicies",
                "iam:GetRolePolicy",
                "iam:GetPolicy",
                "iam:GetPolicyVersion",
                "iam:GetInstanceProfile"
            ],
            "Resource": "*"
        },
        {
            "Sid": "SecretsManagerAccess",
            "Effect": "Allow",
            "Action": [
                "secretsmanager:GetSecretValue"
            ],
            "Resource": "arn:aws:secretsmanager:sa-east-1:5000000000:secret:/git/eks-backup"
        },
        {
            "Sid": "KMSDecryptForSecret",
            "Effect": "Allow",
            "Action": [
                "kms:Decrypt"
            ],
            "Resource": "arn:aws:kms:sa-east-1:5000000000:key/xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
        }
    ]
}
```

## Transit Gateway (replicação cross-account)

Com `recreate_external_routes = true`, no `terraform apply` o lookup resolve o TGW no
destino em cascata: **RAM compartilhado** → **mesmo Name tag** → senão **cria um TGW
novo** idêntico ao da origem (ASN, dns/vpn_ecmp/multicast, route tables customizadas e
rotas estáticas blackhole). Limitações (associações/propagações de route table, outros
attachments como VPN/DX, rotas estáticas para attachment) ficam documentadas no
`CLUSTER-INFO.md` gerado.
