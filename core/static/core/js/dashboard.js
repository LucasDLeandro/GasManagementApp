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
        const ctx = document.getElementById('vendasChart').getContext('2d');
        
        if (vendasChartInstance) {
            vendasChartInstance.destroy();
        }

        vendasChartInstance = new Chart(ctx, {
            type: 'line',
            data: {
                labels: labels,
                datasets: [{
                    label: 'Faturamento (R$)',
                    data: data,
                    borderColor: '#2563eb',
                    backgroundColor: 'rgba(37, 99, 235, 0.1)',
                    borderWidth: 3,
                    pointBackgroundColor: '#2563eb',
                    pointBorderColor: '#ffffff',
                    pointBorderWidth: 2,
                    pointRadius: 5,
                    pointHoverRadius: 7,
                    fill: true,
                    tension: 0.4 // Smooth curves
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: function(context) {
                                return formatCurrency(context.raw);
                            }
                        }
                    }
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        grid: { borderDash: [5, 5], color: '#e5e7eb' },
                        ticks: {
                            callback: function(value) {
                                return 'R$ ' + value;
                            }
                        }
                    },
                    x: {
                        grid: { display: false }
                    }
                }
            }
        });
    }

    loadDashboardStats();
});
