# MUBEC — Calculadora de Horas Extras

Ferramenta para importar espelhos de ponto em PDF e calcular a distribuição de horas extras conforme a **CCT 2024/2025 do Sindicato dos Metalúrgicos de São Paulo**.

---

## Funcionalidades

- **Importação de PDFs** — arraste múltiplos espelhos de ponto de uma vez
- **Leitura inteligente com IA** — extrai nome, HE dias úteis, sábados e feriados automaticamente
- **Faixas progressivas CCT** — distribui as HE nas faixas de 50 / 60 / 80 / 100% automaticamente
- **Sáb / Dom / Feriados** — separados em +100% (até 8h/dia) e +150% (acima de 8h)
- **Exportação em PDF** — relatório completo com identidade visual MUBEC
- **Edição manual** — qualquer campo pode ser corrigido diretamente na tabela

---

## Pré-requisitos

- Python 3.10 ou superior
- Chave de API da Anthropic → [console.anthropic.com](https://console.anthropic.com)

---

## Instalação

```bash
# 1. Clone o repositório
git clone https://github.com/SEU_USUARIO/mubec-he.git
cd mubec-he

# 2. Crie e ative um ambiente virtual
python -m venv venv
source venv/bin/activate        # Linux / Mac
venv\Scripts\activate           # Windows

# 3. Instale as dependências
pip install -r backend/requirements.txt
```

---

## Configuração

Crie um arquivo `.env` na raiz do projeto (ou defina a variável de ambiente):

```bash
# .env
ANTHROPIC_API_KEY=sk-ant-api03-...
```

Ou exporte diretamente no terminal:

```bash
export ANTHROPIC_API_KEY=sk-ant-api03-...   # Linux / Mac
set ANTHROPIC_API_KEY=sk-ant-api03-...      # Windows CMD
```

---

## Executar

```bash
cd backend
uvicorn main:app --reload --port 8000
```

Acesse no navegador: **http://localhost:8000**

---

## Regras da CCT 2024/2025 — Metalúrgicos SP

### Dias úteis (faixas progressivas mensais)

| Faixa         | Acréscimo |
|---------------|-----------|
| Até 25h/mês   | +50%      |
| 25h a 40h/mês | +60%      |
| 40h a 60h/mês | +80%      |
| Acima de 60h  | +100%     |

### Sábado / Domingo / Feriados

| Horas no dia     | Acréscimo |
|------------------|-----------|
| Até 8h diárias   | +100%     |
| Acima de 8h      | +150%     |

> **Sábado**: nesta empresa a jornada é seg–sex (07h–17h / 07h–16h), portanto sábado é dia de descanso semanal remunerado (DSR) e segue o mesmo percentual de domingo/feriado.

---

## Estrutura do projeto

```
mubec-he/
├── backend/
│   ├── main.py           # API FastAPI
│   └── requirements.txt
├── frontend/
│   └── index.html        # Interface web completa
├── .env.example
├── .gitignore
└── README.md
```

---

## Variáveis de ambiente

| Variável           | Descrição                          | Obrigatória |
|--------------------|------------------------------------|-------------|
| `ANTHROPIC_API_KEY`| Chave de API da Anthropic          | Sim         |
| `PORT`             | Porta do servidor (padrão: 8000)   | Não         |

---

## Deploy em servidor (opcional)

Para rodar em produção num servidor Linux:

```bash
# Com gunicorn
pip install gunicorn
gunicorn backend.main:app -w 2 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000
```

Ou use o `systemd` / `supervisor` para manter o processo vivo.

---

## Licença

Uso interno MUBEC Indústria.
