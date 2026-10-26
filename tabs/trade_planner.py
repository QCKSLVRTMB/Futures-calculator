def draw_chart(df_chart, p_a, p_b, p_c, p_d, title="", is_intraday=False, decimals=0, show_trend=False):
    if df_chart.empty:
        return None

    tick_fmt = f",.{decimals}f"

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                        vertical_spacing=0.03, row_heights=[0.8, 0.2])

    # Бары OHLC
    fig.add_trace(go.Ohlc(
        x=df_chart.index, open=df_chart['Open'], high=df_chart['High'],
        low=df_chart['Low'], close=df_chart['Close'],
        increasing_line_color='black', decreasing_line_color='black', name='Рынок'
    ), row=1, col=1)

    # Зигзаг ABCD
    if all(x is not None for x in [p_a, p_b, p_c, p_d]):
        n = len(df_chart)
        step = max(1, n // 3)
        zigzag_x = [
            df_chart.index[0],
            df_chart.index[min(step, n - 1)],
            df_chart.index[min(step * 2, n - 1)],
            df_chart.index[-1],
        ]
        fig.add_trace(go.Scatter(
            x=zigzag_x, y=[p_a, p_b, p_c, p_d],
            mode='lines+markers+text', text=['A', 'B', 'C', 'D'],
            textposition='top center', textfont=dict(size=14, color='blue'),
            line=dict(color='blue', width=3), marker=dict(size=8, color='blue'),
            name='Зигзаг'
        ), row=1, col=1)

    # Объем
    if 'Volume' in df_chart.columns:
        colors = ['black' if c >= o else 'gray' for o, c in zip(df_chart['Open'], df_chart['Close'])]
        fig.add_trace(go.Bar(x=df_chart.index, y=df_chart['Volume'],
                             marker_color=colors, name='Объем'), row=2, col=1)

    # Плашка тренда, подсказки и автоматический канал
    if show_trend:
        trend_text = detect_trend(df_chart)
        
        if trend_text == "Тренд вверх":
            bg_color, font_color = "#198754", "white"
        elif trend_text == "Тренд вниз":
            bg_color, font_color = "#dc3545", "white"
        else:
            bg_color, font_color = "#e2e3e5", "black"

        fig.add_annotation(
            text=trend_text, xref="paper", yref="paper",
            x=0.99, y=0.99, xanchor="right", yanchor="top",
            showarrow=False,
            font=dict(size=14, color=font_color, weight="bold"),
            bgcolor=bg_color, bordercolor="black", borderwidth=1,
            borderpad=6, opacity=0.9
        )

        if not is_intraday:
            add_sperandeo_annotations(fig, df_chart, trend_text, decimals=decimals)
            
            # --- АВТОМАТИЧЕСКИЙ КАНАЛ СПЕРАНДЕО ---
            pivots = get_zigzag_pivots(df_chart, deviation_pct=0.05)
            auto_channel = get_auto_sperandeo_channel(pivots, trend_text)
            
            if auto_channel:
                try:
                    x1_idx = df_chart.index.get_loc(auto_channel['p1'][0])
                    y1 = auto_channel['p1'][1]
                    x2_idx = df_chart.index.get_loc(auto_channel['p2'][0])
                    y2 = auto_channel['p2'][1]
                    x3_idx = df_chart.index.get_loc(auto_channel['p3'][0])
                    y3 = auto_channel['p3'][1]

                    # ВАЖНО: Считаем наклон в пространстве timestamp, а не индексов баров
                    time1 = df_chart.index[x1_idx].timestamp()
                    time2 = df_chart.index[x2_idx].timestamp()
                    time3 = df_chart.index[x3_idx].timestamp()
                    
                    dt_12 = time2 - time1 if time2 != time1 else 1
                    slope_time = (y2 - y1) / dt_12
                    
                    # Вычисляем среднюю длительность бара для корректного продления оси вправо
                    avg_delta = (df_chart.index[-1] - df_chart.index[0]) / max(1, len(df_chart) - 1)
                    dt_end = df_chart.index[-1] + avg_delta * 20
                    time_end = dt_end.timestamp()

                    # Считаем конечные точки лучей на основе реального времени
                    y_ray1_end = slope_time * (time_end - time1) + y1
                    y_ray2_end = slope_time * (time_end - time3) + y3

                    # Луч 1 (стартует строго от p1)
                    fig.add_trace(go.Scatter(
                        x=[df_chart.index[x1_idx], dt_end], y=[y1, y_ray1_end], 
                        mode='lines', name='Линия тренда', line=dict(color='blue', width=2)
                    ), row=1, col=1)
                    
                    # Луч 2 (стартует строго от p3)
                    fig.add_trace(go.Scatter(
                        x=[df_chart.index[x3_idx], dt_end], y=[y3, y_ray2_end], 
                        mode='lines', name='Граница канала', line=dict(color='blue', width=2)
                    ), row=1, col=1)
                except Exception:
                    pass

    fig.update_layout(
        title=title, height=700,
        margin=dict(l=10, r=10, t=50, b=50),
        plot_bgcolor='white', paper_bgcolor='white',
        xaxis_rangeslider_visible=False, showlegend=False,
        hovermode='closest', spikedistance=-1,
    )

    rangebreaks = [dict(bounds=["sat", "mon"])]
    if is_intraday:
        rangebreaks.append(dict(bounds=[23.833, 7], pattern="hour"))

    # Вычисляем общий диапазон оси X для отображения лучей
    if len(df_chart) > 1:
        avg_delta = (df_chart.index[-1] - df_chart.index[0]) / max(1, len(df_chart) - 1)
        x_range = [df_chart.index[0] - avg_delta, df_chart.index[-1] + avg_delta * 20]
    else:
        x_range = None

    fig.update_xaxes(
        showgrid=True, gridcolor='lightgray', rangebreaks=rangebreaks, range=x_range,
        showspikes=True, spikemode='across', spikesnap='cursor',
        spikecolor='gray', spikethickness=1, spikedash='dash',
    )
    
    fig.update_yaxes(
        showgrid=True, gridcolor='lightgray', side='right', tickformat=tick_fmt,
        showspikes=True, spikemode='across', spikesnap='cursor',
        spikecolor='gray', spikethickness=1, spikedash='dash',
    )
    return fig
