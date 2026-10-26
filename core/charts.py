def draw_channel(fig, pts, x_right):
    if len(pts) < 3: return

    # Точки уже отсортированы по времени: pts[0]=A (левая), pts[1]=B (средняя), pts[2]=C (правая)
    t_a, y_a = pts[0][:2]
    t_b, y_b = pts[1][:2]
    t_c, y_c = pts[2][:2]

    x_a, x_c = _ts(t_a), _ts(t_c)

    # Базовая линия (через A и C)
    dt = (x_c - x_a).total_seconds() or 1
    k = (y_c - y_a) / dt

    # Продлеваем вправо
    y_c_ext = y_a + k * (_ts(x_right) - x_a).total_seconds()

    fig.add_shape(type="line", x0=x_a, y0=y_a, x1=x_right, y1=y_c_ext,
                  line=dict(color="blue", width=2), row=1, col=1)

    # Параллельная линия (через B)
    off = y_b - (y_a + k * (_ts(t_b) - x_a).total_seconds())
    fig.add_shape(type="line", x0=x_a, y0=y_a + off, x1=x_right, y1=y_c_ext + off,
                  line=dict(color="blue", width=2), row=1, col=1)

    # Маркеры A, B, C
    fig.add_trace(go.Scatter(
        x=[x_a, _ts(t_b), x_c], 
        y=[y_a, y_b, y_c], 
        mode='markers+text', 
        marker=dict(color='blue', size=10), 
        text=["A", "B", "C"], 
        textposition="top center", 
        showlegend=False
    ), row=1, col=1)
