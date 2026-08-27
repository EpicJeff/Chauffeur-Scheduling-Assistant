"""Graduation: >=10 resolved, act-rate >=60% of the family's actual answers
(acted vs dismissed — expired means unheard, it counts for volume only)."""
from harness import check
from services import storage, mind

def _seed(category, acted, dismissed, expired):
    for i in range(acted + dismissed + expired):
        iid = storage.add_mind_insight({'slug': f'{category}-{i}', 'line': 'x',
                                        'category': category})
        outcome = ('acted' if i < acted else
                   'dismissed' if i < acted + dismissed else 'expired')
        storage.update_mind_insight(iid, {'state': 'retired', 'outcome': outcome})

def scenario_candidate_math():
    storage.mind_insights_table.truncate()
    storage.get_settings = lambda: {'mind_direct_categories': []}
    _seed('supply-gap', acted=7, dismissed=2, expired=3)   # 12 resolved, 78% act
    _seed('overload', acted=2, dismissed=6, expired=2)     # 10 resolved, 25% act
    _seed('young', acted=3, dismissed=0, expired=0)        # only 3 resolved
    cands = mind.graduation_candidates()
    check([c['category'] for c in cands] == ['supply-gap'],
          f"only the proven category graduates, got {cands}")
    c = mind.category_counters()
    check(c['supply-gap']['acted'] == 7, "counters roll up per category")

def scenario_already_graduated_hidden():
    storage.get_settings = lambda: {'mind_direct_categories': ['supply-gap']}
    check(mind.graduation_candidates() == [],
          "a flipped category stops being proposed")

if __name__ == '__main__':
    scenario_candidate_math()
    scenario_already_graduated_hidden()
    print("test_mind_graduation OK")
