# MeuDocMed

Plataforma web de gestão de documentos médicos pessoais, centrada no paciente. Protótipo acadêmico funcional em produção.

**Demo:** [meudocmed.onrender.com](https://meudocmed.onrender.com)

---

## Sobre o projeto

O MeuDocMed parte de um problema real: registros clínicos dispersos entre laboratórios, clínicas e hospitais, sem portabilidade para o paciente. A plataforma centraliza esses documentos e devolve ao paciente o controle sobre quem acessa suas informações, em quais condições e por quanto tempo.

O projeto inclui dois portais distintos — um para pacientes e outro para profissionais de saúde — e uma extensão Chrome para captura de documentos diretamente de portais de saúde como Resulta/Dasa, Einstein Online e sistemas da SMS-Rio.

---

## Funcionalidades

### Paciente
- Upload de documentos em 9 categorias clínicas (exame laboratorial, imagem, laudo, receita, relatório, vacina, internação, cirurgia, outros)
- Validação de arquivos por extensão e por magic number (conteúdo interno)
- Listagem com filtro por categoria, busca por nome e paginação
- Gestão de medicamentos em uso com dose, frequência e via de administração
- Controle de acesso granular: aprovação de solicitações de profissionais com prazo (10/30/60/120 min) e permissão de download configurável
- Revogação de acesso a qualquer momento
- Links de compartilhamento temporário para não cadastrados
- Notificações em tempo real via SSE quando um profissional solicita acesso
- Histórico completo de acessos exportável em PDF
- Exclusão de conta com remoção de todos os dados e arquivos

### Profissional de saúde
- Verificação automática de registro no conselho federal (CFM, COFEN, CFO, COFFITO, CFF) via API externa
- Busca de pacientes por nome, CPF ou cartão SUS
- Solicitação de acesso ao prontuário com mensagem ao paciente
- Visualização de documentos em viewer seguro (sem download quando não permitido)
- Upload de documentos ao prontuário do paciente com acesso ativo

### Armazenamento distribuído
- **Modo padrão:** Cloudinary (armazenamento de arquivos brutos)
- **Modo Shamir:** quando B2 e IDrive estão configurados, o arquivo é cifrado com AES-256-GCM (chave via PBKDF2-HMAC-SHA256, 100.000 iterações) e a chave é dividida em 3 shards via Shamir's Secret Sharing 2-de-3 implementado em GF(2^8). Shard 1 + arquivo cifrado vão para o Backblaze B2, shard 2 para o IDrive e2 e shard 3 para o Cloudinary. Qualquer 2 dos 3 shards reconstroem a chave. Shards com falha são reenviados automaticamente no próximo login.

### Autenticação
- CPF e senha com rate limiting (5 tentativas / 5 min → bloqueio de 10 min)
- Gov.br OAuth 2.0 / OpenID Connect
- Google OAuth 2.0
- Token de API para a extensão Chrome

### Extensão Chrome
- Detecta documentos em portais de saúde (Resulta/Dasa, Einstein, SMS-Rio, e-SUS) e em qualquer PDF aberto no Chrome
- Envia diretamente para o MeuDocMed sem download manual
- Autenticação por token gerado no perfil do paciente

---

## Stack

| Camada | Tecnologia |
|--------|-----------|
| Backend | Python 3.11, Flask 3.0, SQLAlchemy 2.0 |
| Banco de dados | PostgreSQL (produção), SQLite (desenvolvimento) |
| Servidor web | Gunicorn |
| Armazenamento | Cloudinary, Backblaze B2, IDrive e2 |
| Criptografia | AES-256-GCM, PBKDF2-HMAC-SHA256, Shamir SSS em GF(2^8) |
| Auth externo | Gov.br OAuth 2.0, Google OAuth 2.0 |
| PDF | PyMuPDF, fpdf2 |
| E-mail | Flask-Mail |
| Hospedagem | Render |
| Extensão | Chrome Manifest V3 |
| Front-end | HTML/CSS/JS (sem framework), PWA com service worker |

---

## Instalação local

```bash
# 1. Clone e crie o ambiente virtual
git clone https://github.com/seu-usuario/meudocmed.git
cd meudocmed
python -m venv venv
source venv/bin/activate      # Linux/Mac
venv\Scripts\activate         # Windows

# 2. Instale as dependências
pip install -r requirements.txt

# 3. Configure as variáveis de ambiente
cp .env.example .env
# Edite .env com suas credenciais

# 4. Execute
python app.py
```

Acesse: **http://localhost:5000**

---

## Variáveis de ambiente

| Variável | Obrigatória | Descrição |
|----------|-------------|-----------|
| `SECRET_KEY` | Sim | Chave de sessão Flask |
| `DATABASE_URL` | Não | URL do PostgreSQL (padrão: SQLite local) |
| `CLOUDINARY_CLOUD_NAME` | Não | Habilita armazenamento Cloudinary |
| `CLOUDINARY_API_KEY` | Não | |
| `CLOUDINARY_API_SECRET` | Não | |
| `B2_ENDPOINT_URL` | Não | Habilita Shamir SSS (requer B2 + IDrive) |
| `B2_ACCESS_KEY_ID` | Não | |
| `B2_SECRET_ACCESS_KEY` | Não | |
| `B2_BUCKET` | Não | |
| `IDRIVE_ENDPOINT_URL` | Não | |
| `IDRIVE_ACCESS_KEY_ID` | Não | |
| `IDRIVE_SECRET_ACCESS_KEY` | Não | |
| `IDRIVE_BUCKET` | Não | |
| `GOOGLE_CLIENT_ID` | Não | Habilita login com Google |
| `GOOGLE_CLIENT_SECRET` | Não | |
| `GOOGLE_REDIRECT_URI` | Não | |
| `GOVBR_CLIENT_ID` | Não | Habilita login com Gov.br |
| `GOVBR_CLIENT_SECRET` | Não | |
| `GOVBR_REDIRECT_URI` | Não | |
| `MAIL_SERVER` | Não | Habilita e-mail (redefinição de senha) |
| `MAIL_USERNAME` | Não | |
| `MAIL_PASSWORD` | Não | |

---

## Extensão Chrome

1. Abra `chrome://extensions`
2. Ative o **Modo desenvolvedor**
3. Clique em **Carregar sem compactação**
4. Selecione a pasta `chrome-extension/`
5. No MeuDocMed, acesse **Perfil** e gere um token de acesso
6. Cole o token na extensão

---

## Estrutura do projeto

```
meudocmed/
├── app.py                    # Aplicação Flask principal
├── config.py                 # Configurações por ambiente
├── models.py                 # Modelos SQLAlchemy
├── storage_shamir.py         # Shamir SSS + AES-256-GCM
├── requirements.txt
├── Procfile
├── render.yaml
├── routes/
│   ├── auth.py               # Autenticação (CPF, Gov.br, Google)
│   ├── patient.py            # Área do paciente + API da extensão
│   ├── professional.py       # Portal do profissional
│   └── share.py              # Links de compartilhamento público
├── utils/
│   ├── file_utils.py         # Validação por extensão e magic number
│   ├── storage.py            # Abstração Cloudinary / local
│   ├── validators.py         # CPF, registros profissionais e APIs dos conselhos
│   ├── pdf_utils.py          # Geração de PDF do histórico
│   └── notifications.py      # SSE para notificações em tempo real
├── templates/                # Templates Jinja2
├── static/                   # CSS, JS, ícones, manifest.json, sw.js
└── chrome-extension/         # Extensão Chrome (Manifest V3)
    ├── manifest.json
    ├── background.js
    ├── content.js
    ├── popup.html
    └── popup.js
```

---

## Limitações

Este é um protótipo acadêmico. Limitações relevantes:

- O paciente precisa inserir documentos manualmente (sem integração com sistemas de prontuário existentes)
- Não há validação MIME completa dos arquivos enviados
- Sem autenticação multifator
- O armazenamento Shamir depende de três serviços externos simultâneos
- Não há estudo de adesão ou pesquisa de usuário que valide as hipóteses de design

---

## Licença

Desenvolvido para fins acadêmicos. Não substitui prontuário eletrônico oficial.
