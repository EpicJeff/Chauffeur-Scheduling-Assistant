# Porch posts by hand

Owner, 2026-11-25: "I don't know that I can get rid of the posts. They don't show up in the Scene panel as far as I can tell." Approved ("go") for: posts listed under their porch in Scene, with move, add, delete and size. Rule: there is no difference between what generation makes and what a person can make.

## Today

Posts are `porches_detail[].columns = [{at:[x,y], size}]`, absolute building coordinates, no id. Nothing in the editor edits them. One post has no piece of its own: a click picks the porch. A re-read of the plans replaces them unless the porch detail is marked `src.person`. Moving a porch leaves its posts behind.

## Approaches

1. **Posts as pieces with their own operations (chosen).** Copies the pool feature (tree child, own ops, delete) and the roof support handle (drag).
2. Posts as top-level records with ids. Cleaner lists, but a migration of every saved house and every reader. Rejected: no migration without the owner's word.
3. A list of number fields on the porch card only. Cheap, but not selectable in the scene. Rejected: does not answer the ask.

## Record and identity

- Columns stay `{at, size}` with optional `id` (`post:<hex>`). **No ids are minted on load.** The first post operation on a porch mints ids for all its columns. Until then, the client and server both use the derived ref `post:<porchId>:<index>`. Operations accept either; a derived ref that is out of range or whose porch already has ids is refused ("That post is missing.").
- `id` is left out of both bake keys (`bake/geometry_key.js`, `twin_lighting_rev.py`) and out of stored-versus-flat comparisons, so minting alone never marks lighting out of date. Moving, sizing, adding or deleting a post does, correctly.
- An untouched house keeps byte-identical geometry, UVs, keys and stored bytes.

## Operations (`services/twin_porch_posts.py`)

All take `building`, `porch`. Same validation for hand and agent. All mark the detail `_person`, keep the rest of the detail, are one round and one undo step, run in batches, and do not re-derive rooms.

- `add_porch_post {porch, at?, size?, id?}`. Without `at`: the middle of the longest gap between posts (and edge ends) along outline edges that do not lie on a house wall, moved inward by half the size. `size` default: the porch's most common size, else .5.
- `update_porch_post {porch, post, at?, size?}`. At least one of the two.
- `delete_porch_post {porch, post}`.

Limits: size .05 to 3 ft, at most 40 posts per porch, finite `at`. `at` may lie outside the outline (the owner has some): allowed and drawn, as today. A porch with no detail gets an empty one (no default corner posts). Refusals are one plain sentence; invalid values are refused, never defaulted. Flat readers drop a bad column with a note, not the list.

`move_posts_to_roof` accepts columns with ids. Deleting a porch deletes its posts; a batch that deletes a porch and its own posts succeeds.

**Posts follow the porch.** When an operation changes a porch room's outline (move room, joint, wall, edge), each post moves with its nearest outline edge: the edge's displacement at the post's projected position, so a translation moves every post by the same vector, and pulling one edge moves only the posts nearest to it. Ties go to the lower edge index. Posts further than 4 ft from every edge do not follow. The building moving or turning needs nothing.

**Argyle.** `describe` on a porch lists its posts (ref, at, size); the three operations are documented in the edit tool in as few characters as possible. Report the schema size; its gate is already over on main.

## Drawing

Each post is its own piece: kind `porch_post`, id the ref above, `parentPieceId` the porch. Same box, same material (`column`, per porch), same UV seed as today (the porch key), still merged by material. 0 new draws, programs, samplers and triangles. A post's pick proxy wins over the porch's. The porch's own outline box no longer includes the posts; check the framing of a selected porch still looks right. Hiding or locking a porch hides or locks its posts.

## Editor

- **Scene:** rows "Post 1", "Post 2" under the porch (room row or orphan porch row), in stored order. Hide and lock work on a row. Selecting works from the tree and by clicking the post, including while the porch room is focused and in multi-select.
- **Card:** title "Post 2 · Pool Porch". Position X and Y (ft, building), Size (ft), Columns material of the porch with a note that it applies to all posts of this porch, "Select the porch", Delete. Updates in place and keeps scroll and focus.
- **Porch card:** a "Posts" section: count, "Add post" (selects the new post), and one "Size for all posts" field. "Move posts to the roof" is shown disabled with its reason when the porch has posts but does not qualify, instead of vanishing.
- **Move:** drag handle (existing snap rules: grid, outline edges and corners inset by half the size, other posts' lines; Shift frees, as other handles), Move gizmo in plan only, arrow keys as for objects, typed X and Y. Live preview while dragging, commit on release.
- **Delete:** Delete key, right-click, card button, for one or several posts.
- **Sets:** Shift and marquee selection of posts; group move and delete, one undo step. Mixed sets follow the existing group rules.
- Copy and paste, rotation, round posts, per-post material, "Screened" and deck height are **not** in this release.

## Not changed

Automatic creation (`add_porch`, re-reads), screens, gutters and rain read the columns as before; a moved post moves the downspout on it. Porch-to-room-to-porch still discards posts (undo restores them).

## Cost gates (owner's export, High and Low, settled)

0 draws, programs, samplers, triangles against main. Scene build time within 5%. Editor: a post drag frame no slower than a roof support drag. An untouched house: same atlas key and stored bytes.

## Look checks

Pool patio and the owner's back porch: default overview, porch focused, post selected close-up, before and after a move and a delete. Card and Scene panel pictures.

## Split

- **Codex** (worktree `Chauffeur-porch-posts`): operations, ids, follow rule, reads, describe, bake keys, generator piece ownership and picking, `local_ops.js`, tests.
- **Gemini** (worktree `Chauffeur-porch-posts-ui`): Scene, selection, card, handles, gizmo, keys, sets, tests and pictures, against this contract.
- **Claude**: contract, reviews, browser checks, merge, landing.

## Contract for the two halves

- Client piece: `{kind: 'porch_post', id: column.id || 'post:' + porchId + ':' + index, porchId, buildingId, index, piece: column}`. One shared helper `static/twin/porch_posts.js`: `postRef(porch, index)`, `porchPosts(building)` → that list in order, `findPost(building, ref)`. Codex writes it first; Gemini copies it verbatim into the other worktree until the merge.
- Generator `userData`: `{kind: 'porch_post', pieceId: ref, parentPieceId: porchId, part: 'column'}`.
- Operations exactly as above. The server's reply is the usual one; the client reselects by position when refs change from derived to minted (same porch, same index).
