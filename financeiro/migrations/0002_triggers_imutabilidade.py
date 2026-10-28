from django.db import migrations


class VendorAwareRunSQL(migrations.RunSQL):
    """
    RunSQL adaptável ao banco de dados (SQLite e PostgreSQL) para instalação de triggers de imutabilidade.
    Garante que UPDATE e DELETE em LancamentoContabil e PartidaContabil levantem exceção diretamente no banco.
    """
    def __init__(self, **kwargs):
        super().__init__(sql="", reverse_sql="", **kwargs)

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        vendor = schema_editor.connection.vendor
        if vendor == 'sqlite':
            self.sql = """
                CREATE TRIGGER IF NOT EXISTS prevent_update_lancamento
                BEFORE UPDATE ON financeiro_lancamentocontabil
                FOR EACH ROW
                BEGIN
                    SELECT RAISE(FAIL, 'Lançamentos contábeis são estritamente imutáveis no banco de dados.');
                END;

                CREATE TRIGGER IF NOT EXISTS prevent_delete_lancamento
                BEFORE DELETE ON financeiro_lancamentocontabil
                FOR EACH ROW
                BEGIN
                    SELECT RAISE(FAIL, 'Lançamentos contábeis são estritamente imutáveis no banco de dados.');
                END;

                CREATE TRIGGER IF NOT EXISTS prevent_update_partida
                BEFORE UPDATE ON financeiro_partidacontabil
                FOR EACH ROW
                BEGIN
                    SELECT RAISE(FAIL, 'Partidas contábeis são estritamente imutáveis no banco de dados.');
                END;

                CREATE TRIGGER IF NOT EXISTS prevent_delete_partida
                BEFORE DELETE ON financeiro_partidacontabil
                FOR EACH ROW
                BEGIN
                    SELECT RAISE(FAIL, 'Partidas contábeis são estritamente imutáveis no banco de dados.');
                END;
            """
        elif vendor == 'postgresql':
            self.sql = """
                CREATE OR REPLACE FUNCTION prevent_ledger_tampering()
                RETURNS TRIGGER AS $$
                BEGIN
                    RAISE EXCEPTION 'Registros contábeis são estritamente imutáveis no banco de dados.';
                END;
                $$ LANGUAGE plpgsql;

                DROP TRIGGER IF EXISTS prevent_update_delete_lancamento ON financeiro_lancamentocontabil;
                CREATE TRIGGER prevent_update_delete_lancamento
                BEFORE UPDATE OR DELETE ON financeiro_lancamentocontabil
                FOR EACH ROW EXECUTE FUNCTION prevent_ledger_tampering();

                DROP TRIGGER IF EXISTS prevent_update_delete_partida ON financeiro_partidacontabil;
                CREATE TRIGGER prevent_update_delete_partida
                BEFORE UPDATE OR DELETE ON financeiro_partidacontabil
                FOR EACH ROW EXECUTE FUNCTION prevent_ledger_tampering();
            """
        else:
            self.sql = ""
        super().database_forwards(app_label, schema_editor, from_state, to_state)

    def database_backwards(self, app_label, schema_editor, from_state, to_state):
        vendor = schema_editor.connection.vendor
        if vendor == 'sqlite':
            self.reverse_sql = """
                DROP TRIGGER IF EXISTS prevent_update_lancamento;
                DROP TRIGGER IF EXISTS prevent_delete_lancamento;
                DROP TRIGGER IF EXISTS prevent_update_partida;
                DROP TRIGGER IF EXISTS prevent_delete_partida;
            """
        elif vendor == 'postgresql':
            self.reverse_sql = """
                DROP TRIGGER IF EXISTS prevent_update_delete_lancamento ON financeiro_lancamentocontabil;
                DROP TRIGGER IF EXISTS prevent_update_delete_partida ON financeiro_partidacontabil;
                DROP FUNCTION IF EXISTS prevent_ledger_tampering();
            """
        else:
            self.reverse_sql = ""
        super().database_backwards(app_label, schema_editor, from_state, to_state)


class Migration(migrations.Migration):

    dependencies = [
        ('financeiro', '0001_sprint9a_financeiro_base'),
    ]

    operations = [
        VendorAwareRunSQL(),
    ]
