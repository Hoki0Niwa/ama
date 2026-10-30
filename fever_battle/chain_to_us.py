"""What an observed opposing chain still sends at us: its links first offset what is pending on their own side."""


LAUNCH_FRAMES = {'normal': 24, 'fever': 19}    # a link starts its attack object this long after the link begins


def flights_to_us(events, enemy, rate):
    """[(frame, amount)]: when each remaining link of their chain enters our tray, and how much (after their own
    pending takes its share). A link launches `LAUNCH_FRAMES` after it begins; a counter flight already
    observed is in the list at its own frame."""
    pending = enemy.get('normal_confirmed', 0) + enemy.get('normal_unconfirmed', 0)
    if enemy['mode'] == 'fever':
        pending += enemy.get('fever_confirmed', 0) + enemy.get('fever_unconfirmed', 0)
    rest, result = enemy['remainder'], []
    for event in events:
        if event['type'] != 'link':
            continue
        if event.get('source') == 'observed_counter_flight':
            result.append((event['frame'], event['nuisance']))
            continue
        amount, rest = (event['nuisance'], rest) if 'nuisance' in event else divmod(rest + event['points'], rate)
        if pending and amount == 0:
            amount = 1
        taken = min(pending, amount)
        pending -= taken
        if amount - taken:
            result.append((event['frame'] + LAUNCH_FRAMES[enemy['mode']], amount - taken))
    return result


def chain_to_us(events, enemy, rate):
    """Nuisance of the remaining links of their chain that reaches our side (fever_battle/nuisance.h, advance_enemy).

    A link offsets the active tray first (their Fever tray while they are in Fever), then the held normal tray;
    while anything is pending a link counts at least one. Only the rest flies at us. A counter object already in
    flight (`source` observed_counter_flight) has been through that: its amount is what comes back, not offset again."""
    return sum(amount for _, amount in flights_to_us(events, enemy, rate))
