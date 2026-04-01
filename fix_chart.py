with open('components/RealtimeChart.tsx', 'r') as f:
    content = f.read()

correct_props = """interface ChartProps {
  data: {
    timestamps: number[];
    mid_prices: number[];
    ofi: number[];
    ofi_ema: number[];
    macro_sma: number[];
    vwap: number[];
    bb_mid?: number[];
    bb_upper?: number[];
    bb_lower?: number[];
    obi_norm?: number[];
    obi?: number[];
  } | null;
  trades?: any[];
}"""

import re
# Replace the whole block until export function
content = re.sub(
    r'interface ChartProps \{[\s\S]*?export function RealtimeChart',
    correct_props + '\n\nexport function RealtimeChart',
    content
)

with open('components/RealtimeChart.tsx', 'w') as f:
    f.write(content)
