# The house editor: your place, its buildings and its lot

Status: draft for review, 2026-11-07. Amends `docs/superpowers/specs/2026-11-07-house-editor-design.md` (the editor design). It changes how a household sets up its place and what the lot can hold. Everything else in the editor design stands (the build, ghosts and settling, registrations, Argyle's role, cost, the editor's look). It runs as **slice 1b** in two halves (the user, 2026-11-07): **1b-i**, Your place (§3, §4, §6, §9: building cards, documents and photos per part, buildings without drawings, the plot plan read and lot placement in setup, the migration), ships **before** slice 1's live acceptance run so that run tests the real setup; **1b-ii**, the lot's features (§5, §8's drawing palette) and ground levels (§7), ships right after the live run. One design, one scope; the live run only needs 1b-i.

## 1. Intent and why

Slice 1 shipped with a Build dropdown offering "Main house" and "Pool house", and every uploaded page carried one of those two names. The user, on first opening it (2026-11-07): that is specific to this household, and nobody could know it ahead of time. Another family has a main house, a detached garage, a utility shed, a greenhouse and an ADU. The editor is built for other households to install and use, most of them without any 3D experience, and "upload all your plans, then work out which document and page is for what" does not scale to five buildings.

The user's direction: **start from the place, not from a pile of uploads.** The person adds their buildings, and uploads documents to each building. **The lot is its own thing**, with its plot plan or drawing for where everything sits, and photos of the yard so it can be landscaped properly. Walls, masonry fire pits and other things that are built but are not buildings belong to the lot.

The user approved the shape of this in chat (2026-11-07), including: things with no drawings (a shed, a fire pit) can be added in this change; and the list of lot features should cover everything a household is likely to have ("Looks fine" to the list in §5).

## 2. Goals, non-goals, anti-goals

**Goals**
- Any household's place can be described: any number of buildings of any kind, and every built thing on the lot.
- Setup is obvious to someone who has never used a 3D program: add buildings, put documents on them, put the plot plan and yard photos on the lot.
- The agent helps but never decides alone: it suggests buildings and features from the plot plan and photos, and the person confirms.
- Something with no drawings is a first-class citizen: a shed, a greenhouse, a fire pit or a retaining wall can be added by hand, from the plot plan, or from photos.
- Ground levels exist: retaining walls make the yard step up or down, and slopes and steps connect levels (the user's own yard: the front yard, a retaining wall down to the pool level, and the grass about 2 ft lower again).

**Non-goals**
- Survey-grade terrain, contour lines or importing a survey's elevation data.
- Interiors of buildings with no drawings (they are shells: walls, roof, a door; rooms can be drawn later in plan view as for any building).
- Free-form modelling. Every feature is one of the kinds in §5, or the "something else" box, cylinder or slab.

**Anti-goals** (a failure even if it works)
- Names or kinds from this household (house, pool house) built into the product.
- The agent creating buildings or features the person did not confirm.
- A setup that makes the person split PDFs or rename files.
- Losing anything slice 1 can do (repo rule): every slice 1 action keeps a place.

## 3. The place: one lot, many buildings

The editor's first screen, when the place is empty, is **Your place**. It stays reachable from the menu afterwards. It shows:

- **The Lot** card: its documents (plot plan, survey, site drawing), its yard photos, and a count of its features.
- **Buildings**: one card per building, each with its name, kind, documents and photos. **Add building** asks for a name and a kind.
- One **Build** action for the whole place, and a Build action on each card for just that building or just the lot (§6).

**Building kinds** (offered as a list, with "Other" and a free name): Main house, Garage, ADU or guest house, Pool house, Shed, Greenhouse, Barn, Studio or office, Workshop, Other. The kind is a label and a default (a shed defaults to one storey and a simple gable); it never changes how the build works. An **attached** garage, porch or addition is part of the building it is attached to, not a building of its own. **A building is anything you walk into**; everything else built on the lot is a feature (§5).

**Documents belong to the place's parts.** Uploading to a building assigns all its pages to that building; uploading to the lot assigns them to the lot. Each page still gets a role (building pages: floor plan for a named level, roof plan, elevation, other, skip; lot pages: plot plan, survey, landscape plan, other, skip), suggested by the agent and confirmed by the person as in slice 1.

**One PDF often covers several buildings.** Any page can be moved to another building or to the lot with one tap. When the agent suggests roles it also says when a page looks like it belongs elsewhere ("page 7 looks like the garage"); the person decides.

**Photos** can show more than one part: a yard photo often shows the house too. (Designer's call) A photo is tagged with every part it shows. It starts with the part it was uploaded to, the agent's role suggestion can add others ("this one also shows the Main house"), and the person can add or remove tags. A building's reads (pitch, finishes, shell suggestions) use the photos tagged with that building; the lot's reads use the photos tagged with the lot. A photo with no tag goes to the lot.

## 4. The agent suggests, the person confirms

- **From the plot plan:** (Designer's call) when the lot has a confirmed plot plan, Your place offers **Read the plot plan** with its estimated cost; it never starts by itself. That one read also finds the lot outline, the street edge and the plot sheet's scale, so **the lot placement pause moves into setup**: the person sees the lot, the street edge and the suggested footprints over the plot sheet and confirms or drags them, and Build reuses that placement instead of asking again. The read offers what it finds as suggestion cards: each building footprint ("a large building at the front, about 70 by 65 ft"), and each feature it can see (pool, patio, fire pit, walls, driveway). The person names and accepts or dismisses each. An accepted building footprint becomes that building's placement on the lot; an accepted feature arrives as a ghost.
- **Matching existing buildings:** a suggested footprint can be matched to a building the person already added instead of creating a new one.
- **From photos:** the agent can suggest features it sees in yard photos ("a round stone fire pit by the pool") and, for a building with no drawings, its storeys, roof kind and rough pitch. Photo suggestions have no reliable position: they arrive as low-confidence ghosts placed roughly, with a card saying so.
- Nothing becomes part of the place without the person accepting it. Dismissed suggestions are not offered again by the same read.

## 5. What the lot holds: built features

Every feature is a piece like any other: a stable id, ghost or settled state, where it came from (plot plan, photo, person), a confidence and reason when read by a model, and a card with plain fields. Features are edited by hand and by Argyle with the same operations, as slice 1's pieces are.

Four shapes of feature, plus an escape hatch:

- **Lines** (a path of points, a height, a thickness, a material): fence (with gates along it), garden wall, seat wall, retaining wall (§7), hedge, edging or curb, railing.
- **Areas** (an outline, a height above the ground or a depth below it, a material): patio, deck (raised; railing and steps on or off), driveway, walkway or path, steps between levels, pool, built-in spa, pond, sport court, sandbox, raised bed, planting bed, lawn, gravel or mulch area.
- **Open structures** (an outline or posts, a height, a roof kind or open slats): pergola, gazebo, covered patio, carport.
- **Objects** (a spot, a size, a turn): fire pit (round or square), outdoor fireplace, grill island or outdoor kitchen, hot tub, play set, trampoline, pool equipment, AC unit, generator, mailbox, light post, flagpole, tree, shrub.
- **Something else:** a named box, cylinder or slab the person sizes, so nothing a household has is ever impossible to show.

Each kind has sensible default sizes and materials, so placing a fire pit gives a believable fire pit at once.

P0 and slice 1's site items (pool, fire pit, hardscape, beds, edges, fence, planting, furniture) are kept readable and become features of these kinds; P0's yard composition (foundation beds, shrubs, the backdrop tree line) keeps working on top of them, and anything a person placed or moved stays where they put it.

## 6. The build, whole place

**Build** on Your place runs, in order:

1. **The lot.** Placement was confirmed in setup (§4), so Build only settles the lot's accepted features and ground. If the plot plan was never read, Build reads it here and shows the lot placement pause then.
2. **Each building with drawings,** one after another, exactly as slice 1 builds the main house (first-floor scale pause, upper-level registration pauses, walls, openings, rooms, roof sections, pitches from that building's photos). Each finished building is fitted onto its footprint on the lot by shape; it pauses only when the fit is poor or the building has no footprint.
3. **Each building without drawings** becomes a shell (below).
4. **Finishes** as slice 1 (materials from photos, composed planting, the art director when the person runs it).

Each card's own Build runs just that part. Building one part never disturbs another part's settled pieces or anything a person made.

**A building without drawings** is a shell built from:
- its **footprint**: from the plot plan, or drawn by the person on the lot (a rectangle by default, corners can be added), or typed as width by depth;
- a short **card**: storeys, wall height, roof kind (gable, hip, shed, flat), pitch, and where the door is (which side). Photos can fill the card in as a suggestion.
Shells get walls, a roof and one door; windows and rooms can be added by hand like any building's.

The slice 1 targets (§11 of the editor design) still apply to the main house. The pool house's build goes through this same flow.

## 7. Ground levels

- The lot has a **reference height**: by default, the ground at the street edge is 0. The person can change it.
- A **retaining wall**'s card asks **which side is high** and **by how much**. A retaining wall that runs from a lot edge, a building or another retaining wall to another such edge splits the ground there into two levels.
- A **level** is an area of ground at one height. A **slope** is an area whose height changes evenly from one edge to the opposite edge (the person gives the two heights). **Steps** (an area kind) connect two levels.
- A retaining wall that does not reach an edge cannot split anything; it stays a ghost with a plain reason ("this wall needs to reach the lot edge, a building or another wall") until its end is dragged to one.
- (Designer's call) A building's base **follows the ground**: by default it sits on the ground under the centre of its footprint, and moves when that ground's height changes. The person can set a base height on the building's card, and a set value then stays put. A building across a retaining wall sits at its centre's level; walkout and stepped foundations are not modelled in this slice. Every feature sits on the ground at its location. The view and the composition already ask one shared "how high is the ground here" function (slice 1 reserved it, flat everywhere); this slice makes it answer from levels and slopes. Everything that touches the ground uses it.
- Ground levels can come from the plot plan (spot heights and retaining walls the agent reads) or be set by hand.

## 8. What the person sees

- **Your place** (§3) as a full-screen setup view in the editor's style, not an admin form. The 3D scene stays behind it; as buildings and features are accepted they appear on the lot.
- **The floor stack** gains **Lot** (already present) as the place to edit features and ground; each building's floors appear under that building's name.
- **Plan view on the Lot** is where features are drawn: a palette of the §5 kinds grouped as Lines, Areas, Open structures, Objects and Something else. Lines: tap points, tap the last point again to finish. Areas: tap corners, or drag a rectangle. Objects: tap a spot. Everything snaps to the lot edges, building walls, other features and right angles. Then the card opens.
- **Cards** for features show their plain fields (length, height, material; for retaining walls, high side and drop; for slopes, the two heights).
- **Argyle** can do all of it in words: "add a detached garage", "the shed is 10 by 12 with a gable roof", "put a fire pit by the pool", "the retaining wall drops 3 feet toward the back". Every one of these has a hand path, and every hand change is something Argyle can see and explain (repo rules).

## 9. What happens to slice 1's setup

- The Build-target dropdown and the per-page house/pool house selector are replaced by Your place: building cards replace the dropdown, and moving a page replaces the selector. Nothing they did is lost.
- Existing data migrates: pages assigned to `house` become a building named "Main house" (kind Main house); pages assigned to `pool_house` become "Pool house" (kind Pool house); plot pages move to the lot. A plan with existing buildings keeps them under the same ids. (The user will Start over before the live run anyway, but other installs and the test fixtures must migrate cleanly.)
- Upload more, page roles, levels and crops keep working inside each building's and the lot's documents.

## 10. Cost

- (Designer's call) Building this slice records each new read once on the user's own documents (the plot plan suggestion read, a photo suggestion read on a few photos, and the page hint, which rides on the existing role suggestion), capped at $1 in total from the $50; tests then replay those recordings. Everything else needs no model spend.
- The new reads (plot plan suggestions, photo suggestions, page-belongs-elsewhere hints) are small, metered, and shown with their cost before they run, through the existing ledger and checkpoints.
- The $50 budget (development plus acceptance) is unchanged.

## 11. How we know it worked

- The user's place is set up from scratch (Main house, Pool house, the lot with its plot plan and photos) in under 5 minutes, before any build starts, without help.
- A hypothetical place with a main house, detached garage, shed, greenhouse and ADU, two of them with no drawings, can be set up and built to shells, with every building on the lot where the plot plan puts it.
- Every feature kind in §5 can be placed by hand, edited on its card, moved, deleted, and asked for through Argyle.
- The user's yard levels (front yard, retaining wall down to the pool level, about 2 ft lower to the grass) can be expressed, and the buildings and features sit on the right ground.
- The first three points that concern setup and buildings are 1b-i's bar; the slice 1 live acceptance run then happens on that setup. The feature and ground-level points are 1b-ii's bar.

## 12. Left to the builder

- The schema for buildings' kinds and documents, features and ground levels, and the migration from slice 1 and P0 site items.
- The algorithm that turns retaining walls, lot edges and buildings into levels, and how slopes are represented.
- Default sizes, heights and materials for each feature kind, and how each kind is drawn (procedural shapes, library assets where they exist; the no-`transmission` rule stands).
- The prompts and shapes of the plot-suggestion, photo-suggestion and page-belongs-elsewhere reads.
- How the "Your place" view is laid out within the editor's look, and how it hands off to the 3D scene.
- Route names and how the Build for the whole place sequences internally.

## 13. Risks

- **Ground levels** are the hardest new geometry: splitting the lot by walls that meet edges at odd angles. Mitigation: walls that do not split cleanly stay ghosts with a reason; slopes are planar.
- **Size.** Many feature kinds. Mitigation: four shapes of feature share one set of tools and one card pattern; kinds differ in defaults and drawing only.
- **Photo positions** are rough. Mitigation: photo suggestions are always low-confidence ghosts the person places.
- **Delay to the live run.** The main house's build is unchanged; only setup and the lot change, and the live run then tests what other households will see.
