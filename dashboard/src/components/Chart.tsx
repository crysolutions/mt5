import { useEffect, useRef, useState } from "react";
import { createChart, IChartApi, ISeriesApi, LineData, CandlestickData } from "lightweight-charts";

interface Bar {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
}

interface ChartProps {
  symbol: string;
  refreshMs?: number;
}

export function Chart({ symbol, refreshMs = 60000 }: ChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const ema9Ref = useRef<ISeriesApi<"Line"> | null>(null);
  const ema21Ref = useRef<ISeriesApi<"Line"> | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      layout: { background: { color: "#161b22" }, textColor: "#8b949e" },
      grid: { vertLines: { color: "#21262d" }, horzLines: { color: "#21262d" } },
      width: containerRef.current.clientWidth,
      height: 400,
    });

    candleRef.current = chart.addCandlestickSeries({
      upColor: "#3fb950",
      downColor: "#f85149",
      borderVisible: false,
      wickUpColor: "#3fb950",
      wickDownColor: "#f85149",
    });
    ema9Ref.current = chart.addLineSeries({ color: "#58a6ff", lineWidth: 2, title: "EMA9" });
    ema21Ref.current = chart.addLineSeries({ color: "#d2a8ff", lineWidth: 2, title: "EMA21" });
    chartRef.current = chart;

    const onResize = () => {
      if (containerRef.current && chartRef.current) {
        chartRef.current.applyOptions({ width: containerRef.current.clientWidth });
      }
    };
    window.addEventListener("resize", onResize);

    return () => {
      window.removeEventListener("resize", onResize);
      chart.remove();
    };
  }, []);

  useEffect(() => {
    const load = async () => {
      const res = await fetch(`/api/chart/${symbol}?count=120`);
      if (!res.ok) return;
      const data = await res.json();
      const bars: Bar[] = data.bars;
      const ema9: number[] = data.ema9;
      const ema21: number[] = data.ema21;

      const candles: CandlestickData[] = bars.map((b) => ({
        time: b.time as CandlestickData["time"],
        open: b.open,
        high: b.high,
        low: b.low,
        close: b.close,
      }));

      const line9: LineData[] = bars.map((b, i) => ({
        time: b.time as LineData["time"],
        value: ema9[i],
      }));

      const line21: LineData[] = bars.map((b, i) => ({
        time: b.time as LineData["time"],
        value: ema21[i],
      }));

      candleRef.current?.setData(candles);
      ema9Ref.current?.setData(line9);
      ema21Ref.current?.setData(line21);
      chartRef.current?.timeScale().fitContent();
    };
    load();
    const id = setInterval(load, refreshMs);
    return () => clearInterval(id);
  }, [symbol, refreshMs]);

  return <div ref={containerRef} className="chart-container" />;
}
