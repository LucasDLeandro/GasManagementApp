import os
import django
import random
from decimal import Decimal

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from accounts.models import User, UserProfile
from clientes.models import Cliente
from produtos.models import Produto
from logistica.models import Veiculo, Rota
from vendas.models import Venda, ItemVenda

def run():
    print("Criando Clientes...")
    clientes_data = [
        {"cnpj": "11.111.111/0001-11", "nome": "Hospital Santa Fé", "endereco": "Rua da Saúde, 123", "telefone": "11999999999", "estado": "SP", "cidade": "São Paulo", "proprietario": "Dr. Carlos"},
        {"cnpj": "22.222.222/0001-22", "nome": "Indústria Metalúrgica ABC", "endereco": "Av. Industrial, 400", "telefone": "11888888888", "estado": "SP", "cidade": "Guarulhos", "proprietario": "Sr. Roberto"},
        {"cnpj": "33.333.333/0001-33", "nome": "Clínica Odonto Vida", "endereco": "Av. Paulista, 1000", "telefone": "11777777777", "estado": "SP", "cidade": "São Paulo", "proprietario": "Dra. Ana"},
        {"cnpj": "44.444.444/0001-44", "nome": "Oficina do Toninho", "endereco": "Rua dos Mecânicos, 99", "telefone": "11666666666", "estado": "SP", "cidade": "Osasco", "proprietario": "Antonio"},
    ]
    clientes = []
    for cd in clientes_data:
        cliente, _ = Cliente.objects.get_or_create(cnpj=cd['cnpj'], defaults=cd)
        clientes.append(cliente)

    print("Criando Produtos...")
    produtos_data = [
        {"nome": "Cilindro Oxigênio Medicinal", "categoria": "Medicinal", "capacidade": Decimal("10.00"), "unidade_medida": "m³", "preco": Decimal("150.00"), "estoque": 50},
        {"nome": "Cilindro Nitrogênio Industrial", "categoria": "Industrial", "capacidade": Decimal("50.00"), "unidade_medida": "litros", "preco": Decimal("300.00"), "estoque": 20},
        {"nome": "Argônio Solda", "categoria": "Industrial", "capacidade": Decimal("15.00"), "unidade_medida": "m³", "preco": Decimal("250.00"), "estoque": 30},
        {"nome": "Óxido Nitroso", "categoria": "Medicinal", "capacidade": Decimal("5.00"), "unidade_medida": "kg", "preco": Decimal("120.00"), "estoque": 8},
        {"nome": "Mistura para Solda MIG", "categoria": "Industrial", "capacidade": Decimal("10.00"), "unidade_medida": "m³", "preco": Decimal("180.00"), "estoque": 2}, # Baixo estoque para o alerta
    ]
    produtos = []
    for pd in produtos_data:
        produto, _ = Produto.objects.get_or_create(nome=pd['nome'], defaults=pd)
        produtos.append(produto)

    print("Criando Logística (Veículos e Rotas)...")
    veiculos_data = [
        {"placa": "ABC-1234", "modelo": "F-350", "marca": "Ford", "ano": 2018, "capacidade_carga": Decimal("2000.00"), "status": "Ativo"},
        {"placa": "XYZ-9876", "modelo": "Delivery 9.170", "marca": "Volkswagen", "ano": 2021, "capacidade_carga": Decimal("5000.00"), "status": "Ativo"},
        {"placa": "DEF-5678", "modelo": "Sprinter", "marca": "Mercedes", "ano": 2019, "capacidade_carga": Decimal("1500.00"), "status": "Em Manutenção"},
    ]
    veiculos = []
    for vd in veiculos_data:
        veiculo, _ = Veiculo.objects.get_or_create(placa=vd['placa'], defaults=vd)
        veiculos.append(veiculo)

    rotas_data = [
        {"nome": "Rota Capital Leste", "origem": "Base", "destino": "Zona Leste SP", "distancia_km": Decimal("45.00"), "tempo_estimado_horas": Decimal("2.50")},
        {"nome": "Rota Guarulhos", "origem": "Base", "destino": "Guarulhos", "distancia_km": Decimal("30.00"), "tempo_estimado_horas": Decimal("1.50")},
        {"nome": "Rota Osasco", "origem": "Base", "destino": "Osasco", "distancia_km": Decimal("25.00"), "tempo_estimado_horas": Decimal("1.00")},
    ]
    rotas = []
    for rd in rotas_data:
        rota, _ = Rota.objects.get_or_create(nome=rd['nome'], defaults=rd)
        rotas.append(rota)

    print("Garantindo Vendedor...")
    vendedor = User.objects.filter(is_superuser=True).first()
    if not vendedor:
        vendedor = User.objects.create_superuser('admin', 'admin@example.com', 'admin')

    print("Criando Vendas (Histórico e Pendentes)...")
    status_list = ['Pendente', 'Em Separação', 'Em Rota', 'Entregue', 'Finalizada']
    for i in range(15):
        cliente = random.choice(clientes)
        
        # Definir status e, se fizer sentido, atrelar veiculo e rota
        status = random.choice(status_list)
        if status in ['Em Rota', 'Entregue']:
            veiculo = random.choice(veiculos)
            rota = random.choice(rotas)
        elif status == 'Em Separação' and random.random() > 0.5:
            veiculo = random.choice(veiculos)
            rota = random.choice(rotas)
        else:
            veiculo = None
            rota = None
            
        venda = Venda.objects.create(
            cliente=cliente,
            vendedor=vendedor,
            veiculo=veiculo,
            rota=rota,
            status=status
        )
        
        # Criar itens da venda
        num_itens = random.randint(1, 3)
        total_venda = Decimal("0.00")
        for _ in range(num_itens):
            produto = random.choice(produtos)
            qtd = random.randint(1, 5)
            valor_item = produto.preco * qtd
            ItemVenda.objects.create(
                venda=venda,
                produto=produto,
                quantidade=qtd,
                peso_unitario=produto.capacidade,
                valor_unitario=produto.preco,
                valor_total=valor_item
            )
            total_venda += valor_item
            
        venda.valor_total = total_venda
        venda.save()

    print("Dados inseridos com sucesso!")

if __name__ == '__main__':
    run()
