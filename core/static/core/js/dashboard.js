document.addEventListener('DOMContentLoaded', () => {
    function getAuthHeaders() {
        const token = localStorage.getItem('access_token');
        const headers = { 'Content-Type': 'application/json' };
        if (token) headers['Authorization'] = 'Bearer ' + token;
        return headers;
    }

    function formatCurrency(value) {
        return new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' }).format(value);
    }

    let vendasChartInstance = null;

    async function loadDashboardStats() {
        try {
            const res = await fetch('/inicio/api/stats/', { headers: getAuthHeaders() });
            if (!res.ok) throw new Error("Falha ao carregar métricas");
            const data = await res.json();

            // Atualizar Cards
            document.getElementById('dash-faturamento').textContent = formatCurrency(data.faturamento_mes);
            document.getElementById('dash-clientes').textContent = data.clientes_ativos;
            document.getElementById('dash-pendentes').textContent = data.entregas_pendentes;
            document.getElementById('dash-frota').textContent = data.frota_manutencao;

            // Atualizar Alertas
            document.getElementById('dash-estoque').textContent = data.estoque_baixo;
            document.getElementById('dash-frota-alerta').textContent = data.frota_manutencao;

            // Renderizar Gráfico
            renderChart(data.grafico_labels, data.grafico_dados);

        } catch (error) {
            console.error(error);
            document.getElementById('dash-faturamento').textContent = "Erro";
        }
    }

    function renderChart(labels, data) {
        const el = document.getElementById('vendasChart');
        if (!el || typeof ApexCharts === 'undefined') return;
        
        if (vendasChartInstance) {
            try { vendasChartInstance.destroy(); } catch (e) {}
        }

        vendasChartInstance = new ApexCharts(el, {
            chart: {
                type: 'area',
                height: 280,
                toolbar: { show: false }
            },
            series: [{ name: 'Faturamento', data: data }],
            xaxis: { categories: labels },
            stroke: { curve: 'smooth', width: 2 },
            colors: ['#2563eb']
        });
        vendasChartInstance.render();
    }

    loadDashboardStats();
});
