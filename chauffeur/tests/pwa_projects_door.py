"""The phone's one door to Projects & programs (the user's ruling 2026-11-04).

Projects & programs live in Household for everyone who has a Household tab:
an adult's Household draws the Projects & programs card (a pushed screen that
adopts #projects-container), and an explorer / navigator / copilot child's
House tab carries a Projects section. More offers Projects (and My programs)
only to someone with no Household door: a lists-only adult, a child whose
House is lists-only or switched off. A sprout's projects stay in More's own
slot (#pwa-sprout-projects, My things). A helper or a guest has no door.

No side effects at import (no data directory, no storage), so every live test
that walks a person to Projects can share it without touching its own seed.
The door is chosen from the ruling (role, stage, the lists-only flag), never
from which buttons happen to be on the page: a missing door fails the walk.
"""

DOOR = """() => {
    const role = currentMemberRole();
    const listsOnly = typeof houseRevealListsOnly !== 'undefined' && !!houseRevealListsOnly;
    const house = pwaAllowed('chores');
    if (role === 'parent' || role === 'adult') return house && !listsOnly ? 'household' : 'more';
    if (role === 'child') {
        const stage = pwaChildStage();
        if (stage === 'sprout') return 'sprout';
        return house && !listsOnly && ['explorer', 'navigator', 'copilot'].includes(stage) ? 'house' : 'more';
    }
    return 'more';
}"""

LANDED = '#projects-container [data-project-card], #projects-container [data-project-detail]'


def projects_door(page):
    """'household' | 'house' | 'sprout' | 'more' for the signed-in person."""
    return page.evaluate(DOOR)


def open_projects(page, timeout=15000):
    """Walk to Projects through the person's own door; returns the door taken.
    Ends with a project card (or an open project) drawn, as the old
    More > Projects walk did."""
    door = projects_door(page)
    if door == 'household':
        page.locator('#tab-chores').click()
        page.wait_for_function("currentView === 'chores'", timeout=timeout)
        card = page.locator('#house-cards .pwa-house-card[data-card="projects"]')
        card.wait_for(state='visible', timeout=timeout)
        card.click()
        page.wait_for_function("() => !!window.PwaNav && PwaNav.depth() === 1"
                               " && !!document.querySelector('#pwa-stack .pwa-screen #projects-container')",
                               timeout=timeout)
    elif door == 'house':
        page.locator('#tab-chores').click()
        page.wait_for_function("currentView === 'chores'", timeout=timeout)
        section = page.locator('#chores-container .child-section-tabs').get_by_role('button', name='Projects', exact=True)
        section.wait_for(state='visible', timeout=timeout)
        section.click()
        page.wait_for_selector('#chores-container[data-child-section="projects"] #projects-container',
                               state='attached', timeout=timeout)
    elif door == 'sprout':
        page.locator('#tab-more').click()
        page.wait_for_selector('#pwa-sprout-projects [data-project-card], #pwa-sprout-projects [data-project-detail]',
                               timeout=timeout)
        return door
    else:
        page.locator('#tab-more').click()
        page.locator('#pwa-feature-list').get_by_text('Projects', exact=True).first.click()
    page.wait_for_selector(LANDED, timeout=timeout)
    return door
