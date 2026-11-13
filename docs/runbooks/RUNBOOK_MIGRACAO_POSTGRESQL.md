# Runbook: Migração SQLite → PostgreSQL 16 e Backup Diário

Este runbook descreve a migração dos dados do **Baros ERP** de SQLite (`db.sqlite3`) para **PostgreSQL 16**, a configuração do ambiente local (**Estação**) e do servidor EC2 (**VM de produção/teste**), o plano de rollback e a rotina de backup diário com teste de restauração.

> **Nota de segurança:** Nunca grave senhas reais em arquivos versionados no Git. Na VM e na estação, mantenha credenciais apenas no `.env` (`chmod 600`) e no `~/.pgpass` (`chmod 600`).

---

## 1. Instalação e preparação do PostgreSQL 16

### VM de produção/teste (Ubuntu 24.04 EC2)

1. Instalar o PostgreSQL 16 nativo e garantir que escuta **somente em `localhost`** (D1 da D01 — RDS fica para a produção na Sprint 15):
   ```bash
   sudo apt update
   sudo apt install -y postgresql postgresql-contrib
   sudo systemctl enable --now postgresql
   ```
2. Conferir em `/etc/postgresql/16/main/postgresql.conf` que `listen_addresses = 'localhost'` (padrão do Ubuntu; não abrir a porta 5432 no Security Group).
3. Criar usuário e banco de dados da aplicação:
   ```bash
   sudo -u postgres psql <<'SQL'
   CREATE USER baros WITH PASSWORD '<SENHA_FORTE_AQUI>';
   CREATE DATABASE baros OWNER baros ENCODING 'UTF8';
   SQL
   ```
4. Validar conexão local:
   ```bash
   PGPASSWORD='<SENHA_FORTE_AQUI>' psql -h localhost -U baros -d baros -c "SELECT version();"
   ```

### Estação (Windows, sem Docker e sem permissão de administrador)

1. Baixar o pacote **EDB PostgreSQL 16 Windows x86-64 zip archive** e extrair em `C:\Temp\pgsql16\`.
2. Inicializar o cluster UTF-8 (apenas na primeira vez):
   ```pwsh
   C:\Temp\pgsql16\pgsql\bin\initdb.exe -D C:\Temp\pgsql16_data -E UTF8 --locale=C -U postgres -A trust
   ```
3. Subir o servidor em `localhost:5432`:
   ```pwsh
   C:\Temp\pgsql16\pgsql\bin\postgres.exe -D C:\Temp\pgsql16_data -p 5432 -k C:/Temp
   ```
4. Criar role `baros` (com `CREATEDB` para o `pytest-django` criar `test_baros`) e banco `baros`:
   ```pwsh
   C:\Temp\pgsql16\pgsql\bin\psql.exe -h localhost -p 5432 -U postgres -d postgres -c "CREATE ROLE baros WITH LOGIN PASSWORD 'baros_dev_pwd' CREATEDB SUPERUSER;"
   C:\Temp\pgsql16\pgsql\bin\createdb.exe -h localhost -p 5432 -U baros baros
   ```

---

## 2. Migração dos dados do SQLite para o PostgreSQL

### Passo 1 — Preparação e backup do SQLite (`VM de produção/teste`)

1. Atualizar o código para a branch/tag com a Sprint D01 e instalar dependências (`psycopg[binary]`):
   ```bash
   cd /srv/baros/GasManagementApp
   source venv/bin/activate
   pip install -r requirements.txt
   ```
2. **Parar o servidor web/workers** (Gunicorn/Systemd) para impedir escritas durante o corte:
   ```bash
   sudo systemctl stop baros-gunicorn
   ```
3. Fazer backup físico do `db.sqlite3` fora da pasta do projeto:
   ```bash
   sudo mkdir -p /var/backups/baros/sqlite
   sudo cp db.sqlite3 "/var/backups/baros/sqlite/db.sqlite3.pre_pg_$(date +%Y%m%d_%H%M%S)"
   ```

### Passo 2 — Exportação dos dados (`VM de produção/teste`, ainda com SQLite ativo no `.env`)

1. Aplicar eventuais migrações pendentes no SQLite para que o schema bata com os modelos antes do `dumpdata`:
   ```bash
   python manage.py migrate
   ```
2. Registrar a contagem de registros antes da migração:
   ```bash
   python manage.py contar_registros > /tmp/contagem_sqlite.txt
   tail -n 10 /tmp/contagem_sqlite.txt
   ```
3. Exportar os dados em JSON com chaves naturais (excluindo tabelas internas recriadas pelo `migrate`):
   ```bash
   python manage.py dumpdata --all --natural-foreign --natural-primary \
     -e contenttypes -e auth.permission -e admin.logentry -e sessions \
     -o /tmp/baros_dump.json
   ```

### Passo 3 — Virada do `.env` e importação no PostgreSQL (`VM de produção/teste`)

1. Editar `.env` (baseado em `.env.example`) e configurar:
   ```env
   DB_ENGINE=django.db.backends.postgresql
   DB_NAME=baros
   DB_USER=baros
   DB_PASSWORD=<SENHA_FORTE_AQUI>
   DB_HOST=localhost
   DB_PORT=5432
   DB_CONN_MAX_AGE=60
   ```
   Garantir permissão restrita: `chmod 600 .env`.
2. Validar configuração e aplicar todas as migrações no PostgreSQL:
   ```bash
   python manage.py check --database default
   python manage.py migrate
   ```
3. Limpar apenas as tabelas populadas por migrações de dados (`core_planosaas` e `auth_group`) para evitar colisão de chave única com os UUIDs/PKs originais do SQLite, preservando `django_content_type`, `auth_permission` e `django_migrations`:
   ```bash
   PGPASSWORD='<SENHA_FORTE_AQUI>' psql -h localhost -U baros -d baros \
     -c "TRUNCATE TABLE core_planosaas, auth_group RESTART IDENTITY CASCADE;"
   ```
   > **Atenção:** Não use `manage.py flush` antes do `loaddata`, pois `flush` apaga `django_content_type` e quebra a resolução de chaves naturais em `auth.Group`.
4. Importar o dump JSON:
   ```bash
   python manage.py loaddata /tmp/baros_dump.json
   ```
5. Sincronizar as sequências de chaves primárias no PostgreSQL:
   ```bash
   python manage.py sqlsequencereset \
     accounts analytics auth clientes core faturamento financeiro fiscal \
     logistica otp_totp portal_b2b produtos sessions vendas \
     | PGPASSWORD='<SENHA_FORTE_AQUI>' psql -h localhost -U baros -d baros
   ```

### Passo 4 — Verificação pós-migração (`VM de produção/teste`)

1. Comparar a contagem de registros por modelo:
   ```bash
   python manage.py contar_registros > /tmp/contagem_pg.txt
   diff -u /tmp/contagem_sqlite.txt /tmp/contagem_pg.txt
   ```
   O `diff` deve retornar vazio e o `TOTAL:` deve ser idêntico ao do SQLite.
2. Religar o serviço da aplicação e validar nos logs + navegador:
   ```bash
   sudo systemctl start baros-gunicorn
   sudo journalctl -u baros-gunicorn -n 50 --no-pager
   ```
   Testar login, tela inicial, criação de um registro simples (ex.: cliente ou venda de teste em ambiente de homologação) para confirmar que as sequências e travas funcionam.
3. Remover arquivos temporários `/tmp/baros_dump.json`, `/tmp/contagem_sqlite.txt` e `/tmp/contagem_pg.txt`.

---

## 3. Plano de Rollback (`VM de produção/teste`)

Se qualquer falha crítica ocorrer durante ou logo após a virada:

1. Parar a aplicação:
   ```bash
   sudo systemctl stop baros-gunicorn
   ```
2. Comentar ou remover as variáveis `DB_ENGINE`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT` do `.env` (sem `DB_ENGINE`, o `config/settings.py` volta automaticamente para `db.sqlite3`).
3. Caso o `db.sqlite3` tenha sofrido alterações indesejadas, restaurar o backup criado no Passo 1:
   ```bash
   cp /var/backups/baros/sqlite/db.sqlite3.pre_pg_<TIMESTAMP> /srv/baros/GasManagementApp/db.sqlite3
   ```
4. Subir a aplicação:
   ```bash
   sudo systemctl start baros-gunicorn
   ```

---

## 4. Backup diário automatizado (`pg_dump -Fc`) e teste de restauração

### Configuração do backup (`VM de produção/teste`)

1. Criar diretório de backups **fora** da pasta do projeto, com permissão restrita:
   ```bash
   sudo mkdir -p /var/backups/baros/postgres
   sudo chown "$USER":"$USER" /var/backups/baros/postgres
   sudo chmod 700 /var/backups/baros/postgres
   ```
2. Configurar `~/.pgpass` para o usuário que executa o cron (`chmod 600 ~/.pgpass`):
   ```text
   localhost:5432:baros:baros:<SENHA_FORTE_AQUI>
   ```
3. Criar o script `/usr/local/bin/backup_baros_pg.sh` (`chmod 700`):
   ```bash
   #!/usr/bin/env bash
   set -euo pipefail

   BACKUP_DIR="/var/backups/baros/postgres"
   DATA="$(date +%Y%m%d_%H%M%S)"
   ARQ="${BACKUP_DIR}/baros_${DATA}.dump"

   pg_dump -h localhost -p 5432 -U baros -Fc -f "${ARQ}" baros
   chmod 600 "${ARQ}"

   # Retenção de 7 dias
   find "${BACKUP_DIR}" -maxdepth 1 -name "baros_*.dump" -type f -mtime +7 -delete
   ```
4. Agendar execução diária às 03:00 via `crontab -e`:
   ```cron
   0 3 * * * /usr/local/bin/backup_baros_pg.sh >> /var/log/baros_pg_backup.log 2>&1
   ```

### Comando de restauração e teste mensal em banco temporário (`VM de produção/teste` / `Estação`)

Para restaurar um dump `.dump` gerado com `-Fc` em um banco temporário e validar a integridade sem afetar o banco principal:

```bash
# 1. Criar banco temporário
createdb -h localhost -p 5432 -U baros baros_restore_test

# 2. Restaurar o arquivo .dump
pg_restore -h localhost -p 5432 -U baros -d baros_restore_test \
  --no-owner --no-privileges /var/backups/baros/postgres/baros_AAAAMMDD_HHMMSS.dump

# 3. Conferir contagem de registros apontando DB_NAME=baros_restore_test
DB_ENGINE=django.db.backends.postgresql DB_NAME=baros_restore_test \
  DB_USER=baros DB_PASSWORD='<SENHA>' DB_HOST=localhost DB_PORT=5432 \
  python manage.py contar_registros

# 4. Remover banco temporário após validar
dropdb -h localhost -p 5432 -U baros baros_restore_test
```

