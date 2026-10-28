from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from django.views.generic import TemplateView
from django.contrib.auth.mixins import UserPassesTestMixin, LoginRequiredMixin
from django.contrib.auth import authenticate, login, update_session_auth_hash
from django.db import transaction
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from rest_framework_simplejwt.tokens import RefreshToken

from .models import User, UserProfile, DadosTrabalhistas
from .serializers import UserSerializer

@method_decorator(csrf_exempt, name='dispatch')
class CustomLoginAPIView(APIView):
    permission_classes = []
    authentication_classes = []

    def post(self, request):
        username = request.data.get('username')
        password = request.data.get('password')
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            refresh = RefreshToken.for_user(user)
            return Response({
                'refresh': str(refresh),
                'access': str(refresh.access_token),
                'tipo_usuario': user.tipo_usuario,
                'is_superuser': user.is_superuser
            })
        return Response({'detail': 'Credenciais inválidas'}, status=status.HTTP_401_UNAUTHORIZED)

class LoginView(TemplateView):
    template_name = 'accounts/login.html'

from core.permissions import resolve_request_membership

class IsAdminUserType(permissions.BasePermission):
    """
    Permissão baseada exclusivamente no papel do Membership ('ADMIN') ou is_superuser (D10).
    """
    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        if request.user.is_superuser:
            return True
        membership = resolve_request_membership(request)
        return bool(membership and membership.ativo and membership.papel == 'ADMIN')

class AdminRequiredMixin(UserPassesTestMixin):
    def test_func(self):
        user = self.request.user
        if not (user and user.is_authenticated):
            return False
        if user.is_superuser:
            return True
        membership = resolve_request_membership(self.request)
        return bool(membership and membership.ativo and membership.papel == 'ADMIN')


class PessoalTemplateView(AdminRequiredMixin, TemplateView):
    template_name = 'accounts/index.html'

class PerfilUsuarioTemplateView(LoginRequiredMixin, TemplateView):
    template_name = 'accounts/meu_perfil.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        if user.is_authenticated:
            context['user_obj'] = user
            if hasattr(user, 'profile'):
                context['profile'] = user.profile
                if hasattr(user.profile, 'dados_trabalhistas'):
                    context['dados'] = user.profile.dados_trabalhistas
        return context


class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [IsAdminUserType]

    def get_permissions(self):
        if self.action in ['list', 'retrieve', 'alterar_senha', 'atualizar_meu_perfil']:
            return [permissions.IsAuthenticated()]
        return [IsAdminUserType()]

    def get_queryset(self):
        user = self.request.user
        if not user.is_authenticated:
            return User.objects.none()
        from core.tenancy import get_current_tenant
        tenant = get_current_tenant() or getattr(self.request, 'tenant', None)
        if tenant:
            return User.objects.filter(
                memberships__tenant=tenant,
                memberships__ativo=True,
                is_active=True
            ).distinct().order_by('first_name', 'username')
        return User.objects.filter(is_active=True).order_by('first_name', 'username')

    def paginate_queryset(self, queryset):
        if self.request.query_params.get('sem_paginacao') in ('1', 'true', 'True'):
            return None
        return super().paginate_queryset(queryset)

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        # Lógica para criar usuário completo de uma vez (User + Profile + Trabalhistas + Membership)
        data = request.data
        papel = data.get('papel') or data.get('tipo_usuario', 'VENDEDOR')
        
        # 1. Cria o User base
        user = User.objects.create_user(
            username=data.get('username'),
            password=data.get('password'),
            email=data.get('email', ''),
            first_name=data.get('first_name', ''),
            last_name=data.get('last_name', ''),
            tipo_usuario=papel
        )

        # Cria vínculo de Membership no tenant ativo exclusivamente pelo papel (D10)
        from core.tenancy import get_current_tenant
        from core.models import Membership
        tenant = get_current_tenant() or getattr(request, 'tenant', None)
        if not tenant and hasattr(request.user, 'memberships'):
            m_origem = request.user.memberships.filter(ativo=True).first()
            if m_origem:
                tenant = m_origem.tenant

        if tenant:
            valid_papel = papel if papel in dict(Membership.PAPEL_CHOICES) else 'VENDEDOR'
            Membership.objects.create(
                user=user,
                tenant=tenant,
                papel=valid_papel,
                ativo=True
            )

        # 2. Cria o UserProfile
        profile = UserProfile.objects.create(
            user=user,
            cpf=data.get('cpf'),
            rg=data.get('rg'),
            telefone=data.get('telefone', ''),
            birth_date=data.get('birth_date') or None,
            foto_perfil=request.FILES.get('foto_perfil') or None
        )

        # 3. Cria Dados Trabalhistas
        DadosTrabalhistas.objects.create(
            user_profile=profile,
            lotacao=data.get('lotacao', ''),
            matricula=data.get('matricula'),
            empresa=data.get('empresa', ''),
            cargo=data.get('cargo', ''),
            salario=data.get('salario') or None,
            data_admissao=data.get('data_admissao') or None
        )

        serializer = self.get_serializer(user)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @transaction.atomic
    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        data = request.data

        # 1. Atualiza dados base do User
        username = data.get('username')
        if username and username != instance.username:
            if User.objects.filter(username=username).exclude(id=instance.id).exists():
                return Response({'username': ['Este nome de usuário já está em uso.']}, status=status.HTTP_400_BAD_REQUEST)
            instance.username = username

        if 'first_name' in data: instance.first_name = data.get('first_name', '')
        if 'last_name' in data: instance.last_name = data.get('last_name', '')
        if 'email' in data: instance.email = data.get('email', '')

        # Senha provisória opcional na edição
        nova_senha = data.get('password')
        if nova_senha and str(nova_senha).strip():
            instance.set_password(nova_senha)

        papel = data.get('papel') or data.get('tipo_usuario')
        if papel:
            instance.tipo_usuario = papel
        instance.save()

        # 2. Atualiza ou cria Membership no tenant ativo
        from core.tenancy import get_current_tenant
        from core.models import Membership
        tenant = get_current_tenant() or getattr(request, 'tenant', None)
        if not tenant and hasattr(request.user, 'memberships'):
            m_origem = request.user.memberships.filter(ativo=True).first()
            if m_origem:
                tenant = m_origem.tenant

        if tenant and papel:
            valid_papel = papel if papel in dict(Membership.PAPEL_CHOICES) else 'VENDEDOR'
            membership = Membership.objects.filter(user=instance, tenant=tenant, ativo=True).first()
            if membership:
                membership.papel = valid_papel
                membership.save()
            else:
                Membership.objects.create(
                    user=instance,
                    tenant=tenant,
                    papel=valid_papel,
                    ativo=True
                )

        # 3. Atualiza UserProfile
        profile, _ = UserProfile.objects.get_or_create(user=instance)
        if 'cpf' in data: profile.cpf = data.get('cpf')
        if 'rg' in data: profile.rg = data.get('rg')
        if 'telefone' in data: profile.telefone = data.get('telefone', '')
        if 'birth_date' in data: profile.birth_date = data.get('birth_date') or None
        if request.FILES.get('foto_perfil'):
            profile.foto_perfil = request.FILES.get('foto_perfil')
        profile.save()

        # 4. Atualiza DadosTrabalhistas
        dados, _ = DadosTrabalhistas.objects.get_or_create(user_profile=profile)
        if 'lotacao' in data: dados.lotacao = data.get('lotacao', '')
        if 'matricula' in data: dados.matricula = data.get('matricula')
        if 'empresa' in data: dados.empresa = data.get('empresa', '')
        if 'cargo' in data: dados.cargo = data.get('cargo', '')
        if 'salario' in data: dados.salario = data.get('salario') or None
        if 'data_admissao' in data: dados.data_admissao = data.get('data_admissao') or None
        dados.save()

        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    def partial_update(self, request, *args, **kwargs):
        kwargs['partial'] = True
        return self.update(request, *args, **kwargs)

    @action(detail=False, methods=['post'], permission_classes=[permissions.IsAuthenticated])
    def alterar_senha(self, request):
        user = request.user
        nova_senha = request.data.get('nova_senha')
        senha_atual = request.data.get('senha_atual')

        if not senha_atual or not user.check_password(senha_atual):
            return Response({'erro': 'Senha atual incorreta.'}, status=status.HTTP_400_BAD_REQUEST)

        if not nova_senha or len(nova_senha) < 6:
            return Response({'erro': 'A nova senha deve possuir no mínimo 6 caracteres.'}, status=status.HTTP_400_BAD_REQUEST)

        user.set_password(nova_senha)
        user.save()
        # Mantém a sessão válida após a troca de senha (o hash de sessão muda com a senha).
        update_session_auth_hash(request, user)
        return Response({'sucesso': True, 'mensagem': 'Senha alterada com sucesso!'})

    @action(detail=False, methods=['post', 'patch'], permission_classes=[permissions.IsAuthenticated])
    def atualizar_meu_perfil(self, request):
        user = request.user
        telefone = request.data.get('telefone')
        email = request.data.get('email')

        if email:
            user.email = email
            user.save()

        if telefone is not None:
            profile, _ = UserProfile.objects.get_or_create(user=user)
            profile.telefone = telefone
            profile.save()

        return Response({'sucesso': True, 'mensagem': 'Perfil atualizado com sucesso!'})
