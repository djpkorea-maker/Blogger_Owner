def demo_on_start(values):
    # Unknown/absent state always selects the safe demo mode.
    return values.get('R3_START_MODE')!='LIVE'

def auto_start_enabled(values):
    return values.get('R3_AUTO_SYNC')=='1'
