# Relatório de Execução — SPRINT 5A.0
**Módulo:** Higiene de Segurança, Configurações e Fundação Regulatória ANVISA  
**Status:** CONCLUÍDO COM 100% DE SUCESSO  
**Data:** 15/10/2026  

---

## 1. Resumo Executivo

A **Sprint 5A.0** estabeleceu a blindagem de segurança nas configurações do projeto, saneou o controle de versão Git contra artefatos locais/segredos e implementou a fundação regulatória da ANVISA com a modelagem do `PerfilRegulatorioTenant` e `ResponsavelTecnico`.

Foram criados os Registros de Decisão de Arquitetura (**ADRs**) formalizando o modelo matemático do motor de estadia/demurrage e o enquadramento sanitário do sistema. Todos os 36 testes automatizados foram executados com 100% de aprovação.

---

## 2. Entregas Realizadas

### 2.1. Higiene de Segurança e Configurações (`settings.py`, `.env` e Git)
- **Arquivo `.gitignore`:** Criado na raiz do repositório, garantindo exclusão permanente de:
  - Arquivos de segredos locais (`.env`, `.env.*`);
  - Banco de dados SQLite (`db.sqlite3`);
  - Bytecode Python (`__pycache__/`, `*.pyc`);
  - Uploads e mídia privada (`media/`, `private_media/`);
  - Ambientes virtuais e IDEs (`venv/`, `.vscode/`, `.idea/`).
- **Limpeza do Índice Git:** Removidos do rastreamento do Git todos os arquivos `.pyc` legados e o arquivo `db.sqlite3`.
- **Saneamento de `SECRET_KEY` e `DEBUG` em [config/settings.py](file:///c:/Lucas/GasManagementApp/config/settings.py):**
  - Removido o default inseguro de `SECRET_KEY`: agora a leitura é exigida estritamente via `config('SECRET_KEY')` do `python-decouple`.
  - Configurado `DEBUG = config('DEBUG', default=False, cast=bool)`, garantindo que em produção o modo debug permaneça desativado por padrão caso não seja explicitamente declarado.
  - O arquivo [.env](file:///c:/Lucas/GasManagementApp/.env) foi configurado com chaves seguras de desenvolvimento local.
- **Superusuário via Variáveis de Ambiente:** No script [populate_db.py](file:///c:/Lucas/GasManagementApp/populate_db.py), a criação do usuário administrativo principal é lida dinamicamente de `DJANGO_SUPERUSER_USERNAME` e `DJANGO_SUPERUSER_PASSWORD`, eliminando senhas hardcoded em código.

### 2.2. Modelagem Regulatória e Validador Sanitário ANVISA
- **Modelos Criados em [core/models.py](file:///c:/Lucas/GasManagementApp/core/models.py):**
  - **`ResponsavelTecnico`:** Herda de `TenantAwareModel`, registrando `nome_completo`, `conselho_classe` (`CRF` ou `CRQ`), `numero_registro`, `uf_conselho`, `vigencia_inicio`, `vigencia_fim` e `ativo`. Inclui a propriedade `@property def esta_vigente(self)`.
  - **`PerfilRegulatorioTenant`:** Vínculo 1:1 com `Tenant`, contemplando:
    - `modo_operacao`: `ENVASADORA`, `DISTRIBUIDORA`, `MISTO`;
    - `afe_numero` e `afe_validade` (Autorização de Funcionamento ANVISA);
    - `licenca_sanitaria_numero` e `licenca_sanitaria_validade` (VISA Estadual/Municipal);
    - `cbpf_cbpda_numero` e `cbpf_cbpda_validade` (Certificado de Boas Práticas de Fabricação ANVISA);
    - `responsavel_tecnico_vigente`: Chave estrangeira com `on_delete=models.PROTECT` para `ResponsavelTecnico`.
- **Serviço Validador em [core/regulatorio.py](file:///c:/Lucas/GasManagementApp/core/regulatorio.py):**
  - Função `validar_aptidao_medicinal(tenant, exigir_envase=False)`:
    - Lança `ValidationError` descritivo caso o tenant não possua perfil sanitário;
    - Bloqueia operações caso a Licença Sanitária ou AFE estejam vencidas;
    - Bloqueia caso o RT esteja ausente, inativo ou com CRT expirada;
    - Se `exigir_envase=True`, bloqueia empresas com modo `DISTRIBUIDORA` (IN nº 129/2022) ou sem CBPF válido emitido pela ANVISA;
    - Método atalho injetado no modelo: `tenant.validar_aptidao_medicinal(exigir_envase=False)`.

### 2.3. Registros de Decisão de Arquitetura (ADRs)
- Criada a pasta `docs/adr/` com os dois primeiros registros estruturados:
  - **[ADR-001-motor-estadia-demurrage.md](file:///c:/Lucas/GasManagementApp/docs/adr/ADR-001-motor-estadia-demurrage.md):**
    - Especificação matemática: $\text{idade} = D - \text{data\_entrega}$;
    - Isenção por carência de giro ($\text{idade} < \text{dias\_carencia\_giro}$) sem consumo da franquia;
    - Aplicação da franquia global por modelo de cilindro via ordenação FIFO;
    - Cobrança de diárias excedentes e fechamento mensal imutável por snapshot com ajustes futuros em competência posterior.
  - **[ADR-002-marco-regulatorio-e-perfis.md](file:///c:/Lucas/GasManagementApp/docs/adr/ADR-002-marco-regulatorio-e-perfis.md):**
    - Fundamentação da RDC nº 658/2022 e IN nº 129/2022 (Envasadoras) versus RDC nº 887/2024 (Distribuidoras);
    - Procedimentos de registro e notificação via RDC nº 870/2024;
    - Atribuições farmacêuticas conforme Resolução CFF nº 731/2022.

---

## 3. Migrações e Banco de Dados

- **Migração Gerada e Aplicada:**
  - `core.0002_alter_membership_papel_responsaveltecnico_and_more`
  - Aplicação executada com código de saída 0.
- **Povoamento Atualizado:**
  - [populate_db.py](file:///c:/Lucas/GasManagementApp/populate_db.py) atualizado para cadastrar RTs regulares (Dra. Camila Rocha CRF-DF e Dr. Marcos Vinicius CRQ-GO) e Perfis Regulatórios completos para os dois tenants de demonstração.

---

## 4. Evidência dos Testes Automatizados

Comando executado:
```powershell
python manage.py test
```

Resultado da execução:
```text
Creating test database for alias 'default'...
....................................
----------------------------------------------------------------------
Ran 36 tests in 14.849s

OK
Destroying test database for alias 'default'...
Found 36 test(s).
System check identified no issues (0 silenced).
```

### Detalhamento dos Testes da Sprint:
1. `test_bloqueio_tenant_sem_perfil_regulatorio` $\rightarrow$ **Aprovado**
2. `test_bloqueio_licenca_sanitaria_vencida` $\rightarrow$ **Aprovado**
3. `test_bloqueio_afe_anvisa_vencida` $\rightarrow$ **Aprovado**
4. `test_bloqueio_responsavel_tecnico_ausente` $\rightarrow$ **Aprovado**
5. `test_bloqueio_responsavel_tecnico_inativo_ou_expirado` $\rightarrow$ **Aprovado**
6. `test_bloqueio_distribuidora_tentando_envasar_medicinal` $\rightarrow$ **Aprovado**
7. `test_bloqueio_envasadora_sem_cbpf_anvisa_valido` $\rightarrow$ **Aprovado**
8. `test_aprovacao_envasadora_100_regular` $\rightarrow$ **Aprovado**
9. `test_higiene_seguranca_settings` $\rightarrow$ **Aprovado**

---

## 5. Matriz de Arquivos Modificados / Criados

| Arquivo | Descrição |
| :--- | :--- |
| [.gitignore](file:///c:/Lucas/GasManagementApp/.gitignore) | Criação de regras de exclusão para `.env`, `db.sqlite3`, `__pycache__` e `media/` |
| [config/settings.py](file:///c:/Lucas/GasManagementApp/config/settings.py) | Remoção de fallback hardcoded em `SECRET_KEY` e configuração de `DEBUG=False` por padrão |
| [.env](file:///c:/Lucas/GasManagementApp/.env) | Configuração de variáveis locais de segurança |
| [core/models.py](file:///c:/Lucas/GasManagementApp/core/models.py) | Modelagem de `ResponsavelTecnico` e `PerfilRegulatorioTenant` |
| [core/regulatorio.py](file:///c:/Lucas/GasManagementApp/core/regulatorio.py) | Criação do serviço validador `validar_aptidao_medicinal` |
| [core/migrations/0002_alter_membership_papel_responsaveltecnico_and_more.py](file:///c:/Lucas/GasManagementApp/core/migrations/0002_alter_membership_papel_responsaveltecnico_and_more.py) | Migração estrutural dos novos modelos sanitários |
| [core/tests_regulatorio.py](file:///c:/Lucas/GasManagementApp/core/tests_regulatorio.py) | Suíte de testes unitários de conformidade regulatória e segurança |
| [docs/adr/ADR-001-motor-estadia-demurrage.md](file:///c:/Lucas/GasManagementApp/docs/adr/ADR-001-motor-estadia-demurrage.md) | Registro de Decisão de Arquitetura do motor matemático de estadia |
| [docs/adr/ADR-002-marco-regulatorio-e-perfis.md](file:///c:/Lucas/GasManagementApp/docs/adr/ADR-002-marco-regulatorio-e-perfis.md) | Registro de Decisão de Arquitetura do marco regulatório da ANVISA |
| [populate_db.py](file:///c:/Lucas/GasManagementApp/populate_db.py) | Seed de RTs, perfis regulatórios e superusuário via `.env` |
