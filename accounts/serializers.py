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

    class Meta: 
        model = User
        fields = ['id', 'username', 'first_name', 'last_name', 'email', 'tipo_usuario', 'userprofile']