// Detect system theme OR user toggle
const isDarkMode = window.matchMedia('(prefers-color-scheme: dark)').matches;

// Theme colors
const chartColors = {
    text: isDarkMode ? "#e2e8f0" : "#1e293b",
    grid: isDarkMode ? "rgba(255,255,255,0.1)" : "rgba(0,0,0,0.08)",
    score: "#4ade80",
    background: isDarkMode ? "#1e293b" : "#e2e8f0",
    remaining: isDarkMode ? "#475569" : "#cbd5e1"
};

// ----- ATS Gauge Chart -----
function createATSGauge(score){
    const ctx = document.getElementById('atsScore').getContext('2d');

    const gradient = ctx.createLinearGradient(0,0,0,200);
    gradient.addColorStop(0, "#3b82f6");
    gradient.addColorStop(1, "#06b6d4");

    new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: ['Score', 'Remaining'],
            datasets: [{
                data: [score, 100 - score],
                backgroundColor: [gradient, chartColors.remaining],
                borderWidth: 0
            }]
        },
        plugins: [{
            id: "centerText",
            afterDraw(chart) {
                const { ctx, chartArea: { width, height } } = chart;
                ctx.save();
                ctx.fillStyle = chartColors.text;
                ctx.font = "bold 30px Poppins";
                ctx.textAlign = "center";
                ctx.fillText(`${score}%`, width / 2, height / 2 + 10);
            }
        }],
        options: {
            responsive: true,
            cutout: "70%",
            animation: { animateRotate: true, duration: 1500 }
        }
    });
}

// ----- Skill Radar Chart -----
function createSkillRadar(data){
    const ctx = document.getElementById('radarChart').getContext('2d');

    new Chart(ctx, {
        type: "radar",
        data: {
            labels: data.labels,
            datasets: [{
                label: "Skills Match",
                data: data.values,
                borderColor: "#3b82f6",
                backgroundColor: "rgba(59,130,246,0.3)",
                pointBackgroundColor: "#06b6d4",
                borderWidth: 2
            }]
        },
        options: {
            responsive: true,
            scales: {
                r: {
                    min: 0,
                    max: 10,
                    ticks: { display: false },
                    grid: { color: chartColors.grid },
                    angleLines: { color: chartColors.grid },
                    pointLabels: {
                        color: chartColors.text,
                        font: { size: 14 }
                    }
                }
            },
            animation: {
                duration: 1200,
                easing: "easeOutBounce"
            },
            plugins: { legend: { display: false } }
        }
    });
}
