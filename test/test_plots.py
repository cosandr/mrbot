from datetime import timedelta

import matplotlib.pyplot as plt

from ext.internal import Message
from .mock_bot import TestBot


class TestPlot:
    def __init__(self, bot):
        self.bot: TestBot = bot

    async def msg_plot(self):
        """Plot messages sent within a specific timeframe"""
        q = f'SELECT time FROM {Message.psql_table_name} WHERE ch_id != 422473204515209226 ORDER BY time DESC'
        async with self.bot.pool.acquire() as con:
            res = await con.fetch(q)
        dt_curr = res[0]['time']
        td_week = timedelta(days=1)
        x = []  # Time (unix)
        y = []  # Message count
        x_labels = []
        msg_count = 0
        for r in res:
            td_res = dt_curr - r['time']
            # print(f'Days since message: {td_res.days}')
            # print(f'td_res={td_res}')
            if td_res < td_week:
                msg_count += 1
            else:
                x.append(dt_curr.timestamp())
                y.append(msg_count)
                x_labels.append(dt_curr.strftime("%d/%m/%y"))
                # prev = dt_curr.strftime("%d/%m/%y")
                # curr = r["time"].strftime("%d/%m/%y")
                # print(f'{prev} - {curr}: {msg_count}')
                dt_curr = r['time']
                msg_count = 0
        fig = plt.figure(figsize=(30, 10))
        ax = fig.add_subplot(1, 1, 1)
        text_colour = 'xkcd:grey'

        ax.set_facecolor('#36393E')
        fig.set_facecolor('#36393E')

        ax.spines['bottom'].set_color(text_colour)
        ax.spines['left'].set_color(text_colour)
        ax.spines['right'].set_visible(False)
        ax.spines['top'].set_visible(False)

        ax.xaxis.label.set_color(text_colour)
        ax.yaxis.label.set_color(text_colour)
        ax.tick_params(axis='x', colors=text_colour)
        ax.tick_params(axis='y', colors=text_colour)
        # ax.step(x, y, color=text_colour)
        # ax.bar(x, y, color=text_colour)
        ax.plot(x, y, color=text_colour, linewidth=2)
        ax.set_xlim(min(x), max(x))
        ax.set_ylim(0, max(y)+100)
        ax.set_xticks(x)
        ax.set_xticklabels(x_labels, rotation=-90, size=14)
        # ax.set_yticks(np.linspace(0, max(y),))
        ax.set_yticklabels(ax.get_yticks(), size=14)
        plt.show()
        # plt.savefig('/home/andrei/test.png', facecolor=ax.get_facecolor(), box_inches='tight', format='png')
        return
