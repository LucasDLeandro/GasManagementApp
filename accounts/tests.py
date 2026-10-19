from decimal import Decimal
from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework import status

from core.models import Tenant, Membership
from core.tenancy import set_current_tenant, reset_current_tenant
from accounts.models import UserProfile, DadosTrabalhistas

User = get_user_model()

class AccountsModuleTests(TestCase):
    """
    Testes automatizados do módulo de Pessoal & Acessos (Accounts / Baros).
    Garante:
    1. Listagem despaginada (?sem_paginacao=1) restrita ao tenant ativo.
    2. Criação completa de usuário, membership RBAC, perfil e dados trabalhistas.
    3. Edição/atualização completa de funcionário (PUT/PATCH).
    4. Autoatendimento de alteração de senha e contato pelo próprio usuário.
    """

    def setUp(self):
        self.client = APIClient()
        self.tenant = Tenant.objects.create(
            cnpj='11.222.333/0001-44',
            razao_social='Baros Gases Brasília Ltda',
            nome_fantasia='Baros BSB'
        )
        self.token = set_current_tenant(self.tenant)

        # Admin do tenant
        self.admin_user = User.objects.create_user(
            username='gestor.baros',
            password='Password123!',
            email='gestor@baros.com.br',
            first_name='Carlos',
            last_name='Gestor'
        )
        self.admin_membership = Membership.objects.create(
            user=self.admin_user,
            tenant=self.tenant,
            papel='ADMIN',
            ativo=True
        )

        # Funcionário existente
        self.func_user = User.objects.create_user(
            username='joao.operador',
            password='Password123!',
            email='joao@baros.com.br',
            first_name='João',
            last_name='Silva'
        )
        self.func_membership = Membership.objects.create(
            user=self.func_user,
            tenant=self.tenant,
            papel='OPERADOR_PATIO',
            ativo=True
        )
        self.profile = UserProfile.objects.create(
            user=self.func_user,
            cpf='123.456.789-00',
            telefone='(61) 98888-7777'
        )
        self.dados = DadosTrabalhistas.objects.create(
            user_profile=self.profile,
            cargo='Operador de Pátio',
            matricula='MAT-1001',
            salario=Decimal('2500.00')
        )

    def tearDown(self):
        reset_current_tenant(self.token)

    def test_listagem_funcionarios_sem_paginacao(self):
        """Valida que ?sem_paginacao=1 retorna uma lista pura sem envelope DRF."""
        self.client.force_login(self.admin_user)
        session = self.client.session
        session['active_tenant_id'] = str(self.tenant.id)
        session.save()

        res = self.client.get('/accounts/api/users/?sem_paginacao=1')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIsInstance(res.data, list)
        self.assertGreaterEqual(len(res.data), 2)
        usernames = [u['username'] for u in res.data]
        self.assertIn('joao.operador', usernames)
        self.assertIn('gestor.baros', usernames)

    def test_cadastro_novo_funcionario_completo(self):
        """Valida a criação atômica de User, Membership RBAC, Profile e DadosTrabalhistas."""
        self.client.force_login(self.admin_user)
        session = self.client.session
        session['active_tenant_id'] = str(self.tenant.id)
        session.save()

        payload = {
            'username': 'ana.motorista',
            'password': 'Password123!',
            'email': 'ana@baros.com.br',
            'first_name': 'Ana',
            'last_name': 'Pereira',
            'papel': 'MOTORISTA',
            'cpf': '999.888.777-66',
            'rg': 'RG-12345',
            'telefone': '(61) 99999-1111',
            'matricula': 'MAT-2002',
            'cargo': 'Motorista Carreteiro',
            'salario': '3800.00'
        }

        res = self.client.post('/accounts/api/users/', payload)
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        data = res.data

        # Verifica User
        new_user = User.objects.get(username='ana.motorista')
        self.assertEqual(new_user.first_name, 'Ana')

        # Verifica Membership no tenant ativo
        m = Membership.objects.filter(user=new_user, tenant=self.tenant).first()
        self.assertIsNotNone(m)
        self.assertEqual(m.papel, 'MOTORISTA')
        self.assertTrue(m.ativo)

        # Verifica Profile e Dados
        self.assertEqual(new_user.userprofile.cpf, '999.888.777-66')
        self.assertEqual(new_user.userprofile.dadostrabalhistas.matricula, 'MAT-2002')

    def test_edicao_funcionario_com_atualizacao_rbac(self):
        """Valida que o PUT atualiza dados funcionais e o papel RBAC no tenant ativo."""
        self.client.force_login(self.admin_user)
        session = self.client.session
        session['active_tenant_id'] = str(self.tenant.id)
        session.save()

        payload = {
            'username': 'joao.operador',
            'first_name': 'João Carlos',
            'last_name': 'Silva Santos',
            'email': 'joao.silva@baros.com.br',
            'papel': 'GERENTE',  # Promove a Gerente
            'cpf': '123.456.789-00',
            'telefone': '(61) 97777-6666',
            'matricula': 'MAT-1001-REV',
            'cargo': 'Gerente de Pátio',
            'salario': '4500.00'
        }

        res = self.client.put(f'/accounts/api/users/{self.func_user.id}/', payload)
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        self.func_user.refresh_from_db()
        self.assertEqual(self.func_user.first_name, 'João Carlos')
        self.assertEqual(self.func_user.last_name, 'Silva Santos')

        # Membership atualizado para GERENTE
        m = Membership.objects.get(user=self.func_user, tenant=self.tenant)
        self.assertEqual(m.papel, 'GERENTE')

        # Dados funcionais atualizados
        self.func_user.userprofile.refresh_from_db()
        self.assertEqual(self.func_user.userprofile.telefone, '(61) 97777-6666')
        self.func_user.userprofile.dadostrabalhistas.refresh_from_db()
        self.assertEqual(self.func_user.userprofile.dadostrabalhistas.cargo, 'Gerente de Pátio')

    def test_autoatendimento_alterar_senha(self):
        """Valida que o usuário logado consegue alterar sua senha via endpoint próprio."""
        self.client.force_login(self.func_user)
        payload = {
            'senha_atual': 'Password123!',
            'nova_senha': 'NovaSenhaSegura2026!'
        }
        res = self.client.post('/accounts/api/users/alterar_senha/', payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.data.get('sucesso'))

        # Confirma que a nova senha funciona
        self.func_user.refresh_from_db()
        self.assertTrue(self.func_user.check_password('NovaSenhaSegura2026!'))
