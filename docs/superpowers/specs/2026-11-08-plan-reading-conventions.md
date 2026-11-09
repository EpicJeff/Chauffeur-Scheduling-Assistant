# Plan-reading conventions for building a 3D house model (US residential practice)

Date: 2026-11-08. Status: research reference. Audience: whoever writes the plan-reading instructions and geometry checks for the house twin.

## Summary

US residential drawing sets show a house in four kinds of view: plans (floor, roof, site), elevations, sections, and schedules or details. No one view is enough for 3D. The **roof plan** gives the footprint of the roof planes and how they meet. It almost never gives heights. **Elevations and sections** give the plate, floor and ridge heights and the pitches. **Floor plans** give wall positions, openings and stairs. Sizes come from callouts and schedules.

The national standard is the US National CAD Standard (NCS). Its Uniform Drawing System (UDS) has modules for set organization, sheet organization, schedules, drafting conventions, terms and abbreviations, symbols, notations and code conventions [S26, S27]. The NCS is voluntary and paywalled. Residential drafters, plan services and home-design software often depart from it, and textbooks and forums disagree on several points listed below. Every rule here is a default, and an explicit note or legend on the sheet overrides it.

Three findings matter most for roof plans:

- **There is no gable-face symbol.** A gable end is read from the geometry: the ridge runs out to the end edge and no diagonals meet it there [S1].
- **A small triangle at a ridge end is a clipped gable.** If the triangle sits centred on the ridge end and is narrower than the end of the block, it is almost certainly a half-hip (also called a clipped gable or jerkinhead). It is not a marker for a gable [S3, S4, S6].
- **Equal pitches give 45° hips and valleys.** With equal pitches, hips and valleys run at 45° in plan, bisecting the corner they come from [S1, S2]. Any other angle means unequal pitches or a drawing error.

---

## 1. Roof plans

A roof plan is the view looking straight down on the roof. It shows the roof's shape: ridges, hips, valleys, overhangs, slope direction, penetrations and notes. A separate *roof framing plan* shows the members, and is "usually required for complicated roof shapes" [S1]. A roof plan "requires few dimensions": mainly overhangs and openings [S1]. Pitch notes and roofing material go in its notes [S1].

### 1.1 Line types

| Line | How it is drawn | Notes |
|---|---|---|
| Eave / fascia (roof edge) | Solid outline of the whole roof | The outermost closed line is the drip edge or fascia, not the wall [S1]. |
| Walls below | Dashed, inside the roof outline | ETSU labels them "walls obscured below" or "obscured wall support" [S1]. Some drafters leave them off. |
| Ridge | Solid line, often labelled RIDGE | It is the highest horizontal line of the roof. On a gable it runs right out to the end edge [S1]. |
| Hip | Solid diagonal from an outside corner of the roof edge up to a ridge end | "Hip or valley passes through the corner of two intersecting walls" [S1, S2]. |
| Valley | Solid diagonal from an inside (re-entrant) corner up to where the ridges meet | Drawn exactly like a hip. Only the corner it starts from tells them apart [S1, S2]. |
| Rake | The end edge of a gable, perpendicular to the ridge | In plan it lies directly above the gable wall, offset by the rake overhang. Drafters do not give it its own line style. |

The same dashed line means different things on different sheets. On a *floor* plan, a dashed line is often the roof edge or overhang *above* the cut [S31]. On a roof plan it means walls *below*. Ching's general convention is that dashed (hidden) lines show significant items above or below the cutting plane [S30].

### 1.2 Gable ends, and the small triangle question

**How a gable is drawn.** The ridge runs straight to the end edge. Nothing else marks the end: no diagonal, and in the ETSU examples no symbol at all [S1, p.5 and p.18]. The end edge is the rake line.

**A small triangle at the ridge end.** The question was about a triangle narrower than the end of a block, centred on the ridge end. No source I found defines a symbol that marks a gable face this way. NCS, the ETSU course module, the Cyclopedia layout method and the software help pages all leave it out [S1, S2, S4, S5]. The shape does match one specific roof form, with known variants and look-alikes:

| Shape on the roof plan | Roof form | Basis |
|---|---|---|
| A triangle with its apex on the ridge, set back from the end, and its base on the end edge. The base is narrower than the full end, so the two diagonals meet the end edge **inside** the corners. | **Half-hip**, also called **clipped gable** or **jerkinhead**: "a gable, but the upper point of the gable is replaced by a small hip" [S3]. Chief Architect calls it a half-hip: "a hip roof plane builds upward from a partial gable wall" [S4]. | One drafter's own jerkinhead has short hips crossing the gable wall "about the 1/3 points" and in a "40-20-40 ratio" [S6]. That is exactly a centred triangle narrower than the end. The same thread shows that where to dimension these hips is not standardised [S6]. |
| Diagonals start at the corners and stop at the two ends of a short line across the ridge end. The outline is a flat-topped trapezoid, not a triangle. | **Dutch gable / gablet**: a small gable sitting on top of a hip [S3]. Chief Architect calls this a "Dutch hip" [S5]. | "Dutch hip" is used for **both** forms, so it is "easily confused with 'Dutch gable'" [S3]. Decide by the geometry, not the label. ETSU: on a Dutch hip "the overhang line ... intersects hip lines" [S1]. |
| Diagonals start at both **corners** and meet at the ridge end. | Full **hip** end [S1, S2]. | |
| A small triangle or diamond on the **uphill side of a chimney or wall**, not at a ridge end. | **Cricket / saddle**. The IRC requires one on the ridge side of a chimney or penetration more than 30 in. wide [S10]. Software builds it as a separate small roof [S7]. | |
| A triangle labelled with **12** and a number (for example 6) on its legs. | **Pitch symbol**, which is an annotation and not geometry [S1, S9]. | |
| A "V" of two valleys pointing **into** the main roof from the eave side, with a short ridge between them. | **Gable dormer** or a cross gable. Its base is at the dormer face near the eave, not at a ridge end. | See 1.4. |

So read a centred triangle whose base lies on the end edge as a half-hip, and look in the elevations for a clipped gable peak. Only a legend on that sheet that says otherwise overrides this.

### 1.3 Hip versus gable

On a hip end, the diagonals run from the eave corners to the end of the ridge [S1, S2]. When all pitches are equal, each hip is at 45° to the walls ("an angle equal to half the intersecting wall angle") [S1]. The ridge of a rectangular hip roof is then shorter than the building by the building's width. This follows from the Cyclopedia's 45° construction [S2]. A four-sided hip with no ridge is a pyramid hip [S3]. On a gable end there are no diagonals at that end, and the ridge reaches the edge [S1]. If pitches differ, the hip is not at 45°, and a ridge between unequal pitches is off-centre [S1, p.8]. Geometrically, a hip lies where both planes are the same height, so its plan direction from the corner satisfies `run_a × pitch_a = run_b × pitch_b`.

### 1.4 Dormers, cross gables, crickets, shed and flat roofs

- **Cross gable / gable wing.** Its ridge runs perpendicular to the main ridge. Two valleys run from the inside corners to where the wing ridge meets the main roof [S1, p.18; S2]. If the wing ridge is lower than the main ridge, it stops at the valleys' meeting point and does not reach the main ridge [S1, p.18].
- **Dormer.** A dormer is a small roof (gable, hip or shed) on its own walls, standing on the main roof plane. In plan it reads as a mini cross gable with its own short ridge and valleys. A shed dormer is a single plane whose slope arrow is shallower than the main roof's [S8]. The face wall of a dormer is not on the floor plan below. It appears on the upper floor plan and the elevations.
- **Cricket / saddle.** See 1.2. It is required for chimneys or penetrations more than 30 in. wide, measured perpendicular to the slope [S10]. Some state codes measure parallel to the ridge instead [S10 search note]. Its coverings and flashing are noted on the roof plan [S1].
- **Shed roof.** It is a single plane with no ridge. One slope arrow runs from the high wall to the low eave.
- **Flat / low-slope roof.** It has an outline, slope arrows toward drains or scuppers, and a slope note such as 1/4" per foot. The IRC minimum for built-up roofs is 1/4 in 12 [S10]. Asphalt shingles need at least 2:12 [S10]. A plane drawn at under 2:12 with shingles noted is a drawing error.

### 1.5 Slope arrows, pitch symbols, overhangs

- **Slope arrows.** In most practice the arrow points **downhill**, from the ridge toward the eave. Revit's tail is the high end and its head the low end [S8], ETSU's arrows point away from ridges [S1], and a forum survey agrees downhill is the common choice [S9]. There is a minority uphill convention, usually labelled "UP" [S9]. Pitch may be written on the arrow, for example "6:12" or "6/12" [S9].
- **Pitch symbol.** It is a right triangle with **12** on the horizontal leg and the rise on the vertical leg [S1, p.14; S21]. Elevations use it routinely. One reply says pitch is "not normally" called out on a plan view [S9], so it may be missing from the roof plan entirely.
- **Overhangs.** Overhangs are dimensioned on the roof plan [S1], and also in sections or eave details [S1, p.14]. Whether the dimension runs from the wall framing line or from the finished face to the fascia is unsettled. The same doubt shows up in the jerkinhead thread [S6].

### 1.6 Reading rules for roof plans

Collected in the Reading rules section as R1 to R12.

---

## 2. Floor plans

### 2.1 Wall line weights

Cut walls get the heaviest line, or a filled or hatched poché. Edges below the cut are medium, and surface or minor lines are light [S30]. One agency's NCS-based standard assigns its "wide" weight to "major object lines, cut lines" and "thin" to dimensions, hidden objects and centre lines [S25]. On many residential plans exterior and interior walls look the same, so line weight is a weak clue. Wall thickness is a better one, though drawn thickness is a drafting choice.

### 2.2 Dimension strings

- **Placement.** Put as many dimensions as possible outside the plan. Place them far enough out to clear overhangs, and check that "the short dimensions add up to the overall dimension" [S13]. The usual pattern is several parallel strings: openings nearest the wall, then wall jogs and partitions, then the overall. This is common practice. The sources give it only as advice to place strings outside.
- **What they measure to (wood frame).** This varies.
  - Exterior walls go to the **outside face of stud**, the stud line [S13, S14].
  - Interior partitions go to the **centreline** of the partition [S13]. Some drafters use the **face of stud** instead, and "the important thing is to be consistent" [S13]. Some offices dimension to **face of finish** [S13 search note].
  - Windows and doors go to the **centreline** of the opening in wood frame [S13, S14].
- **Masonry.** Dimension to the faces of walls and the edges of openings, not to centrelines [S13, S14]. Masonry veneer over wood frame is dimensioned like wood frame, and only the overall changes [S13, S14].

### 2.3 Opening symbols and swings

A door is drawn as a leaf with a swing arc. A window is a break in the wall with thin sash lines, and a slider is offset glass lines [S17]. Each opening carries a tag: often a number for doors and a letter for windows. The tag keys to a schedule, and openings themselves usually carry no dimensions because sizes live in the schedule [S17].

### 2.4 Window and door size callouts

- **Four-digit codes alternate feet and inches, width first.** "First number is feet, second is inches, third is feet again and the last is inches" [S17].
  - **3068** = 3'-0" × 6'-8".
  - **2868** = 2'-8" × 6'-8" [S17].
  - **2670** = 2'-6" × 7'-0" [S16].
  - A window **2840** = 2'-8" × 4'-0" by the same rule. That reading is inferred; no source states 2840 itself.
  - A prefix **(2)2080** means a pair of 2'-0" × 8'-0" doors [S17].
  - A suffix gives the type, for example **3048DH** = 3'-0" × 4'-8" double-hung [S15].
- **The inch digit is often set small.** "2^8 x 5^2" is a flattened form of 2⁸ × 5², that is 2'-8" × 5'-2". One drafter calls superscript inches "the most correct way" [S15]. Another writes the inch digit "small and underline[d]" [S15]. Other variants: 2/8 (a decoding guide writes door height as "6/8") [S18], 2-8, and 2'8". In plain text, a caret is never an exponent.
- **The same digits can be read as total inches.** A builder who "ordered a 2640 ... got a 26" × 40" window" [S15]. "3648" may be 36" × 48" in a supplier quote but 3'-6" × 4'-8" in a plan program [S15].
- **The code may not be a dimension at all.** Plan services often give manufacturer product numbers [S17]. In Andersen's tilt-wash series, the "28" width column is a 2'-9 5/8" frame with a 2'-10 1/8" minimum rough opening, not 2'-8" [S19]. The sources also disagree on whether a listed size is rough opening [S18], unit (frame) size [S19] or nominal.

### 2.5 Stairs

The stair is drawn with treads, a break line where the plan cut passes through it, and an arrow labelled UP or DN. In US and Canadian practice, the arrow shows the direction of travel *from the floor being viewed* [S20]. An "international" variant always points the arrow upward without words [S20]. The tread count or "nR" (risers) is often noted. Sections give total rise. Stacked stairs can show two break lines [S20].

### 2.6 Ceiling heights

- **Where heights are written.** Room tags often include a height, such as "9'-0" CLG" or "CLG HT" [S18 search note]. A general note sets the default, for example "all ceilings 9'-0" U.N.O.".
- **U.N.O. and its synonyms.** U.N.O. means "Unless Noted Otherwise" and is similar to TYP. (typical) [S18]. UON, "unless otherwise noted", means the same.
- **Special ceilings.** Vaulted, cathedral, tray and coffered ceilings are labelled in the room. Their true shape is in sections and on the reflected ceiling plan, when there is one.

### 2.7 Knee walls and storey-and-a-half

A storey-and-a-half (Cape) puts upper rooms under the roof slope. Short **knee walls** close off the low eave space [S1, p.12; S12]. On the upper floor plan, knee walls are drawn as walls, usually with a height note. The area behind them is attic, and the floor below's roof edge may be dashed. Two code thresholds drive what is drawn:

- **Ceiling height.** No part of a room's required floor area may be under 5 ft. At least half of it must be 7 ft or more [S11].
- **Habitable attic.** The IRC defines a habitable attic as space "not considered a story" when it has at least 70 sq ft, meets R305, and is enclosed by "the roof assembly above, knee walls (if applicable) on the sides and the floor-ceiling assembly below" [S12]. Local zoning may define a half storey differently.

Some drafters draw a dashed line at the 5'-0" or 7'-0" headroom contour. This is weakly sourced practice.

---

## 3. Elevations and sections

- **Level markers.** Vertical positions are given as level tags against a datum. A real 2023 residential set uses these levels [S21]:

  | Level tag | Height |
  |---|---|
  | T.O. 1ST FLR SUB-FLR (the datum) | 0'-0" |
  | T.O. PLATE | 9'-1 1/8" |
  | T.O. 2ND FLR SUB-FLR | 10'-1 1/8" |
  | T.O. WINDOW/DOOR | 6'-10" |
  | T.O. PLATE (second floor) | 18'-2 1/4" |
  | T.O. ROOF | 29'-5" ± |
  | GARAGE SLAB | -3'-0" ± |

  Other sets use "HG T.O. PLT" or "F.F." (finished floor) [S21 search note].
- **Plate heights come from precut studs.** A 92-5/8" precut stud plus three 1-1/2" plates gives 97-1/8" (8'-1 1/8") [S22]. A 104-5/8" stud gives about 109-1/8" [S22]; one JLC answer says 109-1/4". Plates called "8'" or "9'" are therefore usually 8'-1 1/8" or 9'-1 1/8" above subfloor.
- **Floor-to-floor.** It is the plate height plus the depth of the floor framing. In S21 that is 9'-1 1/8" to 10'-1 1/8", about 12 in of floor system.
- **Pitch triangles.** Each roof plane on an elevation carries a 12 / rise triangle. S21 shows 12/12, 8/12 and 6/12 on different planes. Sections repeat them [S1, p.14].
- **Window head heights.** Head heights are usually aligned with door heads and given as a level ("T.O. WINDOW/DOOR 6'-10"") or in the schedule [S21]. The value varies with door height and plate height. No single standard figure is supported.
- **Grade line.** It is the ground line along the bottom of the elevation. Only what is above it can really be seen [S33]. Below-grade foundation is commonly dashed or left out (practice note, not sourced). Height limits are often measured from average grade to the roof midpoint under local zoning, not to the ridge [S21].
- **Elevation names.** Elevations are named either by compass (NORTH ELEVATION) [S21, S33] or as FRONT / REAR / LEFT / RIGHT [S28, S33]. Sheets often show both [S28].

---

## 4. Sheet conventions

- **NCS sheet IDs** have three parts: discipline, sheet type and sequence [S23]. Example: **A-101** = Architectural, type 1, sheet 01.
  - Discipline is one or two letters (A, S, M, E, ...). With a single letter, a hyphen fills the second place.
  - Type digits:

    | Digit | Sheet type |
    |---|---|
    | 0 | General |
    | 1 | Plans |
    | 2 | Elevations |
    | 3 | Sections |
    | 4 | Large-scale views |
    | 5 | Details |
    | 6 | Schedules and diagrams |
    | 7, 8 | User defined |
    | 9 | 3D |

    This table is from [S23, S25].
  - Sequence runs 01 to 99 and may skip numbers.
- **Variants.** A101 without the hyphen, from the AIA CAD Layer Guidelines lineage [S24]. A1.1 or A1.01 in decimal style is common in residential work. A plain A1, A2, ... is also common, and "the same prefix" can mean different things across firms: one set's A1.1 is a site plan [S23 search note]. The S21 set uses A200/A201 for elevations.
- **Titles and scale.** Each view has a title with its own scale, such as "NORTH ELEVATION 1/4"=1'-0"". The title block may say "AS NOTED" [S21]. A graphic scale bar may also appear.
- **North arrow.** A north arrow usually appears on site plans. On floor plans it is optional or by office habit [S28]. Agency standards put north toward the top of the sheet or rotate the arrow to match the view [S25].
- **Which edge is the front.** By convention the front of the house is drawn **along the bottom edge** of the plan sheet [S28, S29]. This is not universal: long houses get rotated, and some offices put north up [S28].
- **Status stamps.** PRELIMINARY, NOT FOR CONSTRUCTION, FOR REFERENCE ONLY and FOR ESTIMATE ONLY [S32] mark an issue that is not final. I found no authoritative definition of these phrases.

---

## 5. Common pitfalls when inferring 3D from 2D

1. **The drawings are not the house.** Construction drawings show intent. As-built and record drawings capture field changes and are a different deliverable [S32].
2. **Roof plans omit heights.** Plate heights, floor depths and often pitches live only on elevations and sections [S1, S9]. Unequal plate heights move the ridge off-centre even with equal pitches [S1, p.9].
3. **Overdetermined geometry hides errors.** With equal pitches, every hip and valley is at 45° and ridge heights follow from span × pitch. A plan that breaks this is either drawn with unequal pitches or simply wrong.
4. **Dimension strings do not close.** Strings may mix reference faces (stud, finish, centreline) [S13], round to the nearest inch, or not add up to the overall dimension, which drafters are told to check [S13].
5. **Size codes are ambiguous** between feet-inches, total inches and manufacturer call numbers [S15, S19].
6. **Dashed lines change meaning between sheets** [S1, S31].
7. **"Dutch hip" names opposite forms** [S3, S5].
8. **Overhangs** may be measured from framing or finish, and rakes and eaves may differ.
9. **Scale.** Half-size prints and "N.T.S." views invalidate measuring off the sheet. Use written dimensions first (practice note). Each view carries its own scale [S21].
10. **Elevation sides.** LEFT and RIGHT names, and stair arrow conventions, vary [S20, S28].

---

## Reading rules

### Roof plans

**R1.** The outermost closed solid line on a roof plan is the roof edge (fascia or drip edge), not a wall. Dashed lines inside it are walls below [S1].

**R2.** A solid line that ends on an outside corner of the roof edge is a **hip**. One that ends on an inside (re-entrant) corner is a **valley**. A horizontal line between them is a **ridge** [S1, S2].

**R3.** If the ridge reaches the end edge and no diagonals meet it there, that end is a **gable**, and the end edge is a rake. Do not look for a gable symbol [S1].

**R4.** If diagonals run from both corners of an end to the ridge end, that end is a **hip** [S1, S2].

**R5.** If a triangle has its apex on the ridge, set back from the end, and its base on the end edge, narrower than the end and centred on the ridge, it is a **half-hip** (clipped gable / jerkinhead). Read the full end as a gable wall topped by a small hip. Confirm against the elevations [S3, S4, S6].

**R6.** If diagonals from the corners stop at the ends of a short line across the ridge end, it is a **Dutch gable / gablet**: a gable above a hip. Classify by geometry, never by the words "Dutch hip" [S3, S5].

**R7.** When all pitches are equal, expect hips and valleys at 45° in plan. When the angle is not 45°, solve `run_a × pitch_a = run_b × pitch_b` for the pitches. If no pitches are given, flag the angle rather than force 45° [S1, S2].

**R8.** Read slope arrows as pointing downhill unless they are labelled UP [S8, S9].

**R9.** A triangle with 12 on one leg and a number on the other is a pitch annotation (rise:12). It is never roof geometry [S1, S9].

**R10.** A small triangle or diamond behind a chimney or at a wall is a cricket. Expect one behind any chimney wider than 30 in. [S7, S10].

**R11.** Treat a plane noted at under 2:12 with shingles, or under 1/4:12 for any roof, as an error to report [S10].

**R12.** Overhang dimensions on the roof plan are horizontal. Record which line they start from. If that line is unstated, assume the framing line and mark the value low-confidence [S1, S6].

### Floor plans

**R13.** On wood-frame plans, read exterior dimensions as running to the outside face of stud, openings to their centrelines, and partitions to centreline. A legend or note overrides this, and face-of-stud or face-of-finish are accepted variants [S13, S14].

**R14.** On masonry, read dimensions to wall faces and opening edges [S13, S14].

**R15.** Check that each string sums to its overall dimension. If it does not, keep the overall and report the gap [S13].

**R16.** Read a four-digit door or window code as feet-inch-feet-inch, width first: 3068 = 3'-0" × 6'-8" [S16, S17].

**R17.** Read superscript, small, underlined or caret-marked digits (2⁸, 2^8, 2/8) as inches: "2^8 x 5^2" = 2'-8" × 5'-2" [S15, S18].

**R18.** Prefer the schedule over the tag. If the tag looks like a manufacturer number (for example TW2846), do not decode it as a dimension. Take sizes from the schedule or mark them unknown [S17, S19].

**R19.** When the feet-inch reading of a code gives an implausible size for the wall it sits in, try the total-inch reading (2640 = 26" × 40"). Flag the ambiguity either way [S15].

**R20.** Read a prefix "(2)" as a pair of leaves, and a suffix (DH, SH, CSMT, FX) as the operation type [S15, S17].

**R21.** An arrow labelled UP or DN points in the direction of travel from the floor shown. An unlabelled arrow may follow the "always points up" convention, so confirm with the floor below [S20].

**R22.** A stair break line marks the plan cut. Treads beyond it belong to the run continuing to another level [S20].

**R23.** Apply a general ceiling-height note (for example "9'-0" CLG U.N.O.") to every room without its own note. U.N.O., UON and TYP all mean "this is the default" [S18].

**R24.** Model vaulted, cathedral and tray ceilings from sections, not from the plan label.

**R25.** On an upper plan, walls with height notes inside the roof outline are knee walls. Space behind them is attic. The plate of a storey-and-a-half is the knee-wall top, not a full storey [S1, S12].

**R26.** In a sloped-ceiling room, expect at least half the required floor area at 7 ft or more and none of it under 5 ft. A model that violates this has probably misread the knee-wall height or the pitch [S11].

### Elevations and sections

**R27.** Take vertical positions from level tags (T.O. PLATE, T.O. SUB-FLR, T.O. WINDOW). Note which datum is 0'-0". Do not measure off the drawing when a tag exists [S21].

**R28.** A plate called "8'" or "9'" is probably 8'-1 1/8" or 9'-1 1/8" above subfloor (precut stud plus three plates) unless it is tagged otherwise [S22].

**R29.** Floor-to-floor = plate height + floor-system depth. Derive it from the two subfloor tags when both exist [S21].

**R30.** Read each roof plane's pitch from the 12 / rise triangle on the elevation, and match each plane to the roof plan [S1, S21].

**R31.** Ridge height above plate = (half the span) × rise / 12 for a symmetrical gable. A tagged T.O. ROOF that disagrees means unequal plates, unequal pitches or a raised heel. Report it [S1, S21].

**R32.** Take window heads from the T.O. WINDOW tag or the schedule. Do not assume a standard figure [S21].

**R33.** The ground line is grade. Anything drawn below it is below-grade work, such as foundation. Do not model it as visible wall [S33].

### Sheets and orientation

**R34.** Parse sheet IDs as discipline + type + sequence (A-101, A101). For A1.1-style or A1-style numbering, use the sheet title, not the number, to decide what the sheet shows [S23, S24].

**R35.** Use the scale in each view title, not the title block's "AS NOTED". Prefer written dimensions over measured ones [S21].

**R36.** Find the front in this order:
1. An elevation titled FRONT.
2. The entry door, porch or driveway, and the street on the site plan.
3. Matching compass-named elevations to the north arrow.
4. As a last resort, the bottom edge of the plan sheet [S28, S29].

**R37.** Resolve LEFT and RIGHT elevations by matching features (windows, chimneys, garage doors) against the plan, never by the name alone [S28].

**R38.** If any sheet carries PRELIMINARY, NOT FOR CONSTRUCTION, FOR REFERENCE ONLY or a similar stamp, lower confidence in that sheet and say so in the result [S32].

### Cross-checks

**R39.** Treat the drawings as design intent. Never claim that a model built from plans matches the built house [S32].

**R40.** Cross-check every roof plane in three views: an outline in the roof plan, a pitch triangle in an elevation, and a height in a section or level tag. If any one is missing, mark the plane as inferred [S1, S9, S21].

**R41.** Read a dashed line by sheet. On a roof plan it means walls below. On a floor plan it means something above: roof edge, beam or upper cabinet [S1, S30, S31].

---

## Sources

Primary or authoritative sources that were actually read are marked ●. Secondary sources (forums, vendor help, blogs) are marked ○ and are used to show practice and its variants. Books listed in "Not consulted" were not available to read.

- **S1** ● Johnson, K. and Uddin, M.M. (2022). *Module 08: Roof Plans*. ENTC 2160 Architectural CAD, East Tennessee State University. Page numbers are PDF pages. https://dc.etsu.edu/entc-2160-oer/10 (PDF: https://dc.etsu.edu/context/entc-2160-oer/article/1009/viewcontent/Roof_Plans.pdf)
- **S2** ● *Cyclopedia of Architecture, Carpentry and Building*, vol. 1-3, "Layout of Roof Plan". https://chestofbooks.com/architecture/Cyclopedia-Carpentry-Building-1-3/Layout-Of-Roof-Plan.html
- **S3** ○ Wikipedia, "Hip roof" (half-hip, gablet, Dutch-hip naming). https://en.wikipedia.org/wiki/Hip_roof
- **S4** ○ Chief Architect KB-00736, "Generating a Half-Hip Roof Automatically". https://www.chiefarchitect.com/support/article/KB-00736/generating-a-half-hip-roof-automatically.html
- **S5** ○ Chief Architect KB-00749, "Creating a Dutch Hip Roof". https://www.chiefarchitect.com/support/article/KB-00749/creating-a-dutch-hip-roof.html
- **S6** ○ ChiefTalk forum, "Standard practice?: half-hip or jerkinhead gable" (2019). https://chieftalk.chiefarchitect.com/topic/23129-standard-practice-half-hip-or-jerkinhead-gable
- **S7** ○ Chief Architect KB-03017, "Creating a Roof Cricket". https://www.chiefarchitect.com/support/article/KB-03017
- **S8** ○ Noble Desktop, "Revit roof plan: adding dimensions, slope arrows" (arrow tail = high end). https://blog.nobledesktop.com/learn/revit/revit-roof-plan-adding-dimensions-slope-arrows-and-adjusting-cut-plane ; Autodesk Revit help, "Creating a Dormer Using Slope Arrows". https://help.autodesk.com/cloudhelp/2016/ENU/Revit-Model/files/GUID-701B3821-2371-4E61-A508-2D76145566A5.htm
- **S9** ○ SketchUp forum, "Labelling slopes" (downhill arrow more common, 12-triangle). https://forums.sketchup.com/t/labelling-slopes-architects-and-civil-engineers-help-requested/91720 ; Archinect, "dimensioning roof slope in plan view". https://archinect.com/forum/thread/150128425/advice-on-dimensioning-roof-or-terrain-slope-in-plan-view ; CADTutor, "how to indicate roof design on site plan". https://cadtutor.net/forum/topic/48789-how-to-indicate-roof-design-on-site-plan
- **S10** ● International Residential Code, ch. 9: R903.2.2 crickets and saddles; R905.2.2 asphalt shingle slope (2:12 minimum); R905.9.1 built-up roof slope (1/4:12). https://codes.iccsafe.org/content/IRC2021P2/chapter-9-roof-assemblies . Cricket text as reproduced in an ICC code-change document: https://www.iccsafe.org/wp-content/uploads/IBC-S_S3-S84.pdf . The search note on state variants (California, Wisconsin) is from secondary summaries.
- **S11** ● IRC R305 Ceiling height, City of Boise handout. https://www.cityofboise.org/media/3924/434-irc-code-section-r305-ceiling-height.pdf
- **S12** ● City of Pittsburgh PLI bulletin, "Habitable Attic" (quotes the IRC definition). https://pittsburghpa.gov/files/assets/city/v/1/pli/documents/pli-bulletins/bulletin_-_habitable_attic.pdf
- **S13** ● US Navy training manual, "Dimensioning a Floor Plan" (Basic Engineering, reproduced by Integrated Publishing). https://tpub.com/engbas/10-11.htm . The face-of-finish variant is from forum discussion: https://forums.augi.com/archive/index.php/t-59740.html
- **S14** ○ Lydia Sloan Cline (drafting textbook author), "Architectural Dimensioning". https://blogs.jccc.edu/lcline/2012/04/15/architectural-dimensioning/
- **S15** ○ ChiefTalk, "Window size dimensions in schedule and current industry standards" (superscript and underlined inches, 2640 misorder, 3648 ambiguity). https://chieftalk.chiefarchitect.com/topic/9544-window-size-dimensions-in-schedule-and-current-industry-standards ; ChiefTalk 47514. https://chieftalk.chiefarchitect.com/topic/47514-window-and-doors-labeled-in-inches-instead-of-feet-and-inches
- **S16** ○ ChiefTalk, "Why is the formatted size in a door schedule different" (2670 = 2'6" × 7'0"). https://chieftalk.chiefarchitect.com/topic/42154-why-is-the-formatted-size-in-a-door-schedule-different-from-the-actual-door-size
- **S17** ○ Sater Design Collection, "Detail Floor Plan Explained (4 of 11)" (plan service). https://saterdesign.com/blogs/news/117364807-detail-floor-plan-explained-4-of-11
- **S18** ○ I Stock House Plans, "Decoding Guide" (U.N.O., TYP, CLG, 6/8, window = rough opening). https://sites.google.com/site/istockhouseplans/resources/decoding-guide . The "CLG HT" room-label usage is from a secondary search result, not this page.
- **S19** ● Andersen 400 Series Tilt-Wash Double-Hung sizing table (2013-2014 Product Guide, as filed with the Detroit HDC). https://detroitmi.gov/sites/detroitmi.localhost/files/hdc-submitted-materials/2024-11/andersen%20sizing-windows--400series-tilt-washhungfull-frame_0.pdf
- **S20** ○ Graphisoft Community, "Stairs Reversal of Fortune" (US direction-of-travel versus "always up"). https://community.graphisoft.com/t5/Modeling/Stairs-Reversal-of-Fortune/td-p/110804 ; Noble Desktop, stair break lines. https://blog.nobledesktop.com/learn/blueprint-reading/understanding-stair-drawings-in-floor-plans-stacked-stairs-and-switchback-stair-tower-explained
- **S21** ● Santini Residence, sheets A200/A201 Exterior Elevations, Mark A. Day PE (2023), Town of Marlborough NY filing. https://townofmarlboroughny.gov/DocumentCenter/View/7731/12-Santini-Residence-229-Mt-Zion-Rd-Architectural-Sheets--10-27-23 . The "HG T.O. PLT" and "F.F." variants come from search snippets of a San Antonio OHP filing and an Oakville ON sheet; those were not opened.
- **S22** ○ JLC, "Precut Stud Lengths". https://www.jlconline.com/how-to/framing/precut-stud-lengths_o ; Fine Homebuilding, "Do Precut Studs Make Sense?". https://www.finehomebuilding.com/project-guides/framing/do-precut-studs-make-sense
- **S23** ○ Archtoolbox, "Construction Document Sheet Numbers" (NCS/UDS format summary). https://www.archtoolbox.com/construction-document-sheet-numbers/ . The A1.1 variants are from search results on a Burbank CA submittal and an Ontario guide.
- **S24** ● F. Heitzman, Triton College, "Organization of Drawings in a Set of Construction Documents" (after the AIA *CAD Layer Guidelines*, 2nd ed., 1997). https://academics.triton.edu/faculty/fheitzman/dwgnumb.html
- **S25** ● City of Fort Wayne, *CADD5 Drafting Conventions* (2015), which declares conformance to NCS v5 UDS modules 4 and 7 (line widths, north arrow, sheet types). https://utilities.cityoffortwayne.org/resources/pdfs/CADD5__Drafting_Conventions.pdf
- **S26** ● US Dept. of Veterans Affairs, *VHA CAD Standard Application Guide* (lists UDS Modules 1-8). https://www.wbdg.org/FFC/VA/VACAD/VHACADAppGuide.pdf
- **S27** ● CSI, "National CAD Standard" overview. https://www.csiresources.org/standards/ncs
- **S28** ○ ChiefTalk, "Compass rose on the plans" (front-at-bottom, FRONT/LEFT/RIGHT/REAR versus compass, plan-checker requests). https://chieftalk.chiefarchitect.com/topic/24882-compass-rose-on-the-plans/
- **S29** ○ Designing Buildings Wiki, "Floor plan" (front typically along the lower side of the sheet; a UK source). https://www.designingbuildings.co.uk/wiki/Floor_plan
- **S30** Ching, F.D.K., *Architectural Graphics*, 6th ed. (Wiley, 2015), ch. 3 "Multiview Drawings", Floor Plans: line weights, and dashed lines for elements above or below the cut. The book was not available online. The dashed-line statement was confirmed only through a secondary quotation, so verify it against the book.
- **S31** ○ Graphisoft Community, "showing roof eaves lines and the lower part of hip lines" (dashed roof above on floor plans). https://community.graphisoft.com/t5/Modeling/showing-roof-eaves-lines-and-the-lower-part-of-hip-lines/m-p/206949/highlight/true
- **S32** ● Cornell Facilities, "Drawing types" (construction versus as-built versus record; "For Estimate Only" sets). https://fcs.cornell.edu/archive/drawing-types
- **S33** ○ House Plans Helper, "How to read elevations". https://houseplanshelper.com/how-to-read-elevations.html

**Not consulted** (named in the brief; full texts are paywalled and were not available here). Use them to confirm or override the above:
- NCS v6 UDS Module 4 (Drafting Conventions), Module 5 (Terms and Abbreviations) and Module 6 (Symbols).
- *Architectural Graphic Standards for Residential Construction*.
- Kicklighter, *Architecture: Residential Drafting and Design* (Goodheart-Willcox).
- Jefferis and Madsen, *Architectural Drafting and Design* (Cengage). The ETSU module [S1] appears to follow it.
- Wakita and Linde, *The Professional Practice of Architectural Working Drawings* (Wiley).
