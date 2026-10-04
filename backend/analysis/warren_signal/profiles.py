"""Per-ticker Warren Blue Up profiles, transcribed from the ThinkorSwim scripts in ~/warren-thinkscripts/
(rp_RSI_WVF_SPYSTUDY.ts, rp_RSI_WVF_QQQSTUDY.ts, rp_RSI_WVF_TQQQSTUDY.ts, rp_RSI_Pivot_WVF_TECLSTUDY.ts).
The ThinkScript is the source of truth: every number below is copied from the script, nothing is tuned,
"fixed" or taken from any other implementation. The symbol -> profile lookup lives in the data layer
(data/warren_signal_data.py::profile_for); this module only defines the profiles.

Each script defines (the ANY-TICKER script has neither, only `scanOverSold4 = RSI_Num[1] <= 12`):

    blueUp        = scanOverSold1 or scanOverSold2
    scanOverSold1 = RSI_Num[1] <= a_rsi and WVF_Buy >= a_wvf and ADX_Between and volume <= a_cap
                 or RSI_Num[1] <= b_rsi and volume <= b_cap and ADX_Between
    scanOverSold2 = volume > Volume_Num and ADX <= 29.66 and RSI_Num < 40
                 or RSI_Num < X and volume > Volume_Num
                 or paraDrop <= .70 and pivotLow and WVF_Between(25, 27)
                 [or RSI_Num[1] < 16.3 or WVF_Buy >= 17]        # QQQ only, trailing and ungated

Known quirks, ported on purpose (do not "correct" without the owner's decision):
- TQQQ's SOS1 volume cap is 692200 -- TECL's number, copied into a ticker whose 2h bars trade tens of millions
  of shares -- so its scanOverSold1 can essentially never fire. TQQQ's `Volume_Num` is 300M.
- For SPY, TQQQ and TECL, SOS1 branch a is a strict subset of branch b (a lower RSI cutoff plus WVF with the
  same other conditions), so it never contributes on its own. It is kept because the script has it.
- QQQ's two trailing ORs gate on nothing (no volume, no ADX).
- SPY and QQQ also add `RSI_Num > 50` to scanOverbought; redundant with pivotHigh (RSI > 70), so there is no
  profile field for it and the down-arrow logic is identical across all five scripts.
"""

from .types import QuietBlueBranch, TickerBlueRules, WarrenProfile

# rp_RSI_WVF_SPYSTUDY.ts: ADX_Between(ADX, 43, 46); Volume_Num = 70000000
SPY = WarrenProfile(
    name="spy",
    rules=TickerBlueRules(
        adx_lo=43.0,
        quiet_branches=(
            QuietBlueBranch(rsi1_max=18.0, wvf_min=10.0, volume_max=24_000_000),
            QuietBlueBranch(rsi1_max=21.034, volume_max=24_000_000),
        ),
        volume_num=70_000_000,
        sos2_rsi_b=14.0,
    ),
)

# rp_RSI_WVF_QQQSTUDY.ts: ADX_Between(ADX, 43, 46); Volume_Num = 70000000
QQQ = WarrenProfile(
    name="qqq",
    rules=TickerBlueRules(
        adx_lo=43.0,
        quiet_branches=(
            QuietBlueBranch(rsi1_max=18.0, wvf_min=10.0, volume_max=24_000_000),
            QuietBlueBranch(rsi1_max=18.0, volume_max=10_000_000),
        ),
        volume_num=70_000_000,
        sos2_rsi_b=16.1,
        ungated_rsi1_lt=16.3,
        ungated_wvf_min=17.0,
    ),
)

# rp_RSI_WVF_TQQQSTUDY.ts: ADX_Between(ADX, 39.2, 46); Volume_Num = 300000000; SOS1 volume cap 692200 (see above)
TQQQ = WarrenProfile(
    name="tqqq",
    rules=TickerBlueRules(
        adx_lo=39.2,
        quiet_branches=(
            QuietBlueBranch(rsi1_max=21.0, wvf_min=13.9, volume_max=692_200),
            QuietBlueBranch(rsi1_max=21.034, volume_max=692_200),
        ),
        volume_num=300_000_000,
        sos2_rsi_b=16.61,
    ),
)

# rp_RSI_Pivot_WVF_TECLSTUDY.ts: ADX_Between(ADX, 39.2, 46); Volume_Num = 4000000. Identical to TQQQ's script
# apart from Volume_Num.
TECL = WarrenProfile(
    name="tecl",
    rules=TickerBlueRules(
        adx_lo=39.2,
        quiet_branches=(
            QuietBlueBranch(rsi1_max=21.0, wvf_min=13.9, volume_max=692_200),
            QuietBlueBranch(rsi1_max=21.034, volume_max=692_200),
        ),
        volume_num=4_000_000,
        sos2_rsi_b=16.61,
    ),
)
