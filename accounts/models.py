from django.db import models
from django.contrib.auth.models import AbstractUser

class User(AbstractUser):
    class TipoUsuario(models.TextChoices):
        ADMIN = 'ADMIN', 'Admin'
        GERENTE = 'GERENTE', 'Gerente'
        SUPERVISOR = 'SUPERVISOR', 'Supervisor'
        ENCARREGADO = 'ENCARREGADO', 'Encarregado'
        VENDEDOR = 'VENDEDOR', 'Vendedor'
        ATENDENTE = 'ATENDENTE', 'Atendente'
        CARREGADOR = 'CARREGADOR', 'Carregador'
        CLIENTE = 'CLIENTE', 'Cliente'

        
    tipo_usuario = models.CharField(max_length=25, choices=TipoUsuario.choices)

    def __str__(self):
        return f"{self.username} - ({self.get_tipo_usuario_display()})"
# Create your models here.

class UserProfile(models.Model):
    cpf = models.CharField(max_length=11, unique=True)
    rg = models.CharField(max_length=9, unique=True)
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    
    birth_date = models.DateField(null=True, blank=True)
    telefone = models.CharField(max_length=15, blank=True)

    def __str__(self):
        return self.user.username

class DadosTrabalhistas(models.Model):
    user_profile = models.OneToOneField(UserProfile, on_delete=models.CASCADE)
    lotacao = models.CharField(max_length=100, blank=True)
    matricula = models.CharField(max_length=20, unique=True)
    empresa = models.CharField(max_length=100, blank=True)
    cargo = models.CharField(max_length=100, blank=True)
    data_admissao = models.DateField(null=True, blank=True)
    data_demissao = models.DateField(null=True, blank=True)
    salario = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    def __str__(self):
        return f"{self.user_profile.user.username} - {self.cargo}"