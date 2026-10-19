from rest_framework import serializers
from .models import User, UserProfile, DadosTrabalhistas

class DadosTrabalhistasSerializer(serializers.ModelSerializer):
    class Meta:
        model = DadosTrabalhistas
        fields = ['lotacao', 'matricula', 'empresa', 'cargo', 'data_admissao', 'data_demissao', 'salario']

class UserProfileSerializer(serializers.ModelSerializer):
    dadostrabalhistas = DadosTrabalhistasSerializer(read_only=True)

    class Meta:
        model = UserProfile
        fields = ['cpf', 'rg', 'birth_date', 'telefone', 'foto_perfil', 'dadostrabalhistas']

class UserSerializer(serializers.ModelSerializer):
    userprofile = UserProfileSerializer(read_only=True)
    papel = serializers.SerializerMethodField()

    class Meta: 
        model = User
        fields = ['id', 'username', 'first_name', 'last_name', 'email', 'tipo_usuario', 'papel', 'userprofile']

    def get_papel(self, obj):
        request = self.context.get('request')
        tenant = None
        if request:
            from core.tenancy import get_current_tenant
            tenant = get_current_tenant() or getattr(request, 'tenant', None)
        if tenant:
            m = obj.memberships.filter(tenant=tenant, ativo=True).first()
            if m:
                return m.papel
        m = obj.memberships.filter(ativo=True).first()
        return m.papel if m else getattr(obj, 'tipo_usuario', 'VENDEDOR')