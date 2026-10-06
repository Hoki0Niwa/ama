"""What the normal board's triggers need, as a report beside a decision.

The decision itself is made by the builder or by the tactical search; this
only tells which colors the longest trigger waits for and what the chosen
placement spent of them.
"""
def inspect(native, own):
    return native.ask(dict(op='normal_colors', field=own['field'], queue=own['queue'],
                           confirmed=own['confirmed']))


def report(native, own, reply):
    analysis = inspect(native, own)
    reply['normal_color_needs'] = analysis['needs']
    chosen = next((c for c in analysis['candidates'] if (c['x'], c['r']) == (reply['x'], reply['r'])), None)
    if chosen is not None:
        reply['needed_color_consumed'] = chosen['needed_color_consumed']
    return reply
