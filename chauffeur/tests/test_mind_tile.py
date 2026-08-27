"""The board tile never carries a sensitive row — boards have no identity."""
from harness import check
from services import storage, home_board
import datetime

def scenario_tile_filters_sensitive():
    storage.mind_insights_table.truncate()
    storage.add_mind_insight({'slug': 'a', 'line': 'normal', 'category': 'c',
                              'sensitivity': 'normal'})
    storage.add_mind_insight({'slug': 'b', 'line': 'secret', 'category': 'c',
                              'sensitivity': 'sensitive'})
    data = home_board._tile_mind(datetime.datetime.now())
    lines = [i['line'] for i in data['insights']]
    check(lines == ['normal'], f"sensitive absent from tile payload, got {lines}")

def scenario_tile_registered():
    check(home_board._BUILDERS.get('mind') is home_board._tile_mind,
          "tile type 'mind' registered")

if __name__ == '__main__':
    scenario_tile_filters_sensitive()
    scenario_tile_registered()
    print("test_mind_tile OK")
