from rest_framework import viewsets, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from django.views.generic import TemplateView
from django.contrib.auth.mixins import UserPassesTestMixin, LoginRequiredMixin
from django.contrib.auth import authenticate, login
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

class IsAdminUserType(permissions.BasePermission):
    """
    Permissão customizada para permitir acesso apenas a usuários com tipo_usuario == 'ADMIN' ou is_superuser.
    """
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and (request.user.tipo_usuario == 'ADMIN' or request.user.is_superuser))

class AdminRequiredMixin(UserPassesTestMixin):
    def test_func(self):
        return self.request.user.is_authenticated and (self.request.user.tipo_usuario == 'ADMIN' or self.request.user.is_superuser)


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

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        # Lógica para criar usuário completo de uma vez (User + Profile + Trabalhistas)
        data = request.data
        
        # 1. Cria o User base
        user = User.objects.create_user(
            username=data.get('username'),
            password=data.get('password'),
            email=data.get('email', ''),
            first_name=data.get('first_name', ''),
            last_name=data.get('last_name', ''),
            tipo_usuario=data.get('tipo_usuario', 'VENDEDOR')
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
