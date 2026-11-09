# PDOK BAG GeoPackage: schema and mapping (VA-33)

Read from `data/bron/bag-light_2026-11-01.gpkg` with stdlib `sqlite3` (3.45.3), `mode=ro`.
Measured 2026-11-07 and 2026-11-08 on the laptop while other agents were running, so the
timings are upper-end figures, not benchmarks.

## The file

| | |
| --- | --- |
| Size | 7.827.132.416 bytes (the expected size) |
| SHA-256 | `d52279acd00a104b1790e0c86b189779b5e6b0ef657f56cfe491aa262d05cc3b` |
| Format | GeoPackage 1.4 (`application_id` 1196444487, `user_version` 10400), page size 4096 |
| Geometry | EPSG:28992 (RD New), the same as the WFS pull |

**The file's own date** is in `gpkg_contents.last_change`: `2026-10-31T23:00:12.563Z`, the same
on all five feature tables. That is **2026-11-01 00:00:12 in Amsterdam** and agrees with the file
name. Convert it to Europe/Amsterdam before taking the date: the UTC date is one day early. The
file has no `gpkg_metadata` table. The modification time on disk (2026-11-06) is the download
date, not the data's date. *Reading:* `last_change` is when the file was built, which is the
closest thing the file records to a data date.

## Tables and row counts

Feature tables. `feature_id` is `INTEGER PRIMARY KEY AUTOINCREMENT` and `geom` is `GEOMETRY`
in all of them.

| Table | Rows | Geometry | Other columns |
| --- | ---: | --- | --- |
| `verblijfsobject` | 9.998.456 | POINT | see below |
| `pand` | 11.447.522 | POLYGON | see below |
| `standplaats` | 54.737 | POLYGON | as `ligplaats` |
| `ligplaats` | 12.755 | POLYGON | `rdf_seealso`, `identificatie`, `status`, `openbare_ruimte_naam`, `openbare_ruimte_naam_kort`, `huisletter`, `toevoeging`, `postcode`, `woonplaats_naam`, `nummeraanduiding_hoofdadres_identificatie`, `openbare_ruimte_identificatie`, `woonplaats_identificatie`, `bronhouder_identificatie` (all TEXT), `huisnummer` (INT) |
| `woonplaats` | 2.503 | MULTIPOLYGON | `rdf_seealso`, `identificatie`, `status`, `woonplaats`, `bronhouder_identificatie` (all TEXT) |

`verblijfsobject`, in column order: `rdf_seealso` TEXT, `identificatie` TEXT, `oppervlakte` INT,
`status` TEXT, `gebruiksdoel` TEXT, `openbare_ruimte_naam` TEXT, `openbare_ruimte_naam_kort` TEXT,
`huisnummer` INT, `huisletter` TEXT, `toevoeging` TEXT, `postcode` TEXT, `woonplaats_naam` TEXT,
`bouwjaar` INT, `pand_identificatie` TEXT, `pandstatus` TEXT,
`nummeraanduiding_hoofdadres_identificatie` TEXT, `openbare_ruimte_identificatie` TEXT,
`woonplaats_identificatie` TEXT, `bronhouder_identificatie` TEXT.

`pand`: `rdf_seealso` TEXT, `identificatie` TEXT, `bouwjaar` INT, `status` TEXT, `gebruiksdoel`
TEXT, `oppervlakte_min` INT, `oppervlakte_max` INT, `aantal_verblijfsobjecten` INT.
4.853.650 panden have no VBO: `gebruiksdoel` and both `oppervlakte_*` are NULL, the count is 0.

GeoPackage bookkeeping: `gpkg_contents` 5 rows, `gpkg_extensions` 5, `gpkg_geometry_columns` 5,
`gpkg_spatial_ref_sys` 4, `sqlite_sequence` 5 (`name`, `seq`).

R-tree per feature table: a virtual table `rtree_<t>_geom(id, minx, maxx, miny, maxy)` and three
shadow tables, `_node(nodeno INTEGER PRIMARY KEY, data)`, `_parent(nodeno INTEGER PRIMARY KEY,
parentnode)` and `_rowid(rowid INTEGER PRIMARY KEY, nodeno)`.

| R-tree of | `_rowid` | `_node` | `_parent` |
| --- | ---: | ---: | ---: |
| `verblijfsobject` | 9.998.456 | 306.547 | 306.546 |
| `pand` | 11.447.522 | 347.320 | 347.319 |
| `standplaats` | 54.737 | 1.742 | 1.741 |
| `ligplaats` | 12.755 | 397 | 396 |
| `woonplaats` | 2.503 | 79 | 78 |

**No index exists on any data column.** The only indexes are the autoindexes on `gpkg_*` tables.
Any `WHERE` on `identificatie`, `pand_identificatie` or `woonplaats_naam` is a full table scan.

## Mapping: WFS snapshot field to GeoPackage column

Everything comes from `verblijfsobject`. **No join is needed.** Comparison column: August WFS
snapshot against this file on the 61.946 Delft VBO's present in both (all of them, not a sample).

| Pipeline field | GeoPackage column | Differ | Notes |
| --- | --- | ---: | --- |
| `identificatie` | `identificatie` | 0 | TEXT, always 16 characters, unique |
| `rdf_seealso` | `rdf_seealso` | 0 | |
| `pandidentificatie` | `pand_identificatie` | 37 | **Name differs.** Never NULL, never comma-separated |
| `oppervlakte` | `oppervlakte` | 157 | INT, never NULL |
| `status` | `status` | 259 | |
| `gebruiksdoel` | `gebruiksdoel` | 12 | **Comma-separated, as in the WFS** |
| `bouwjaar` | `bouwjaar` | 71 | INT, never NULL. Copied from the pand |
| `pandstatus` | `pandstatus` | 1.180 | Copied from the pand |
| `openbare_ruimte` | `openbare_ruimte_naam` | 0 | **Name differs.** Not `_kort` |
| `huisnummer` | `huisnummer` | 1 | |
| `huisletter` | `huisletter` | 3 | NULL where the WFS has `""` (55.413 rows) |
| `toevoeging` | `toevoeging` | 0 | NULL where the WFS has `""` (60.419 rows) |
| `postcode` | `postcode` | 0 | NULL where the WFS has `""` (1.649 rows) |
| `woonplaats` | `woonplaats_naam` | 0 | **Name differs** |
| `_x`, `_y` | parsed from `geom` | 0 | Largest difference 0,0 m |
| `gemeentecode` | `bronhouder_identificatie` | n/a | The CBS gemeentecode without `GM`, 4 digits; 342 codes in the 2026-11-01 file, the same set as CBS 03759ned (VA-34, VA-65) |

The "Differ" counts exclude NULL against `""`. `selectie.py` reads those fields with `or ""`, so
NULL is harmless there. VA-34 should still store `""` so a snapshot has the WFS's shape.

No field the pipeline uses is missing.

**`gebruiksdoel`:** 241.553 VBO's nationally hold more than one value, 417 of them in Delft (also
417 in August). No spaces around the commas. The 11 values are exactly the keys of `FUNCTIEGROEP`
in `selectie.py`. Values are not always in alphabetical order: 395 of Delft's 417 are.

**`geom`:** a GeoPackage blob, readable with `struct`: `GP`, version, flags, SRS as int32, then
the envelope, then WKB. In all 61.963 Delft rows: SRS 28992, no envelope, WKB type 1 (point). The
national rows were not decoded, so VA-34 should read the envelope size from the flags byte.

**`bouwjaar` and `pandstatus` match the `pand` table:** 0 mismatches across Delft's 61.963 VBO's
and 24.006 panden, and every Delft pand exists in `pand`. Nationally, 23 VBO rows carry a
`pandstatus` (`Pand gesloopt` 13, `Pand ten onrechte opgevoerd` 8, `Niet gerealiseerd pand` 2)
that occurs on no row of `pand`, so an inner join would lose them. Not traced further.

## A VBO in more than one pand

**Each VBO is one row with one pand.** `identificatie` has no duplicates (`GROUP BY`, 65 s) and
`pand_identificatie` never holds a comma. A second pand of a multi-pand VBO is not in the row.

The losses are visible: the sum of `pand.aantal_verblijfsobjecten` is 10.035.469, which is 37.013
more than the VBO rows. In Delft, 150 of 24.006 panden count more VBO's than link to them and none
count fewer. *Reading:* those 37.013 are links dropped by the one-pand-per-VBO form. The file does
not say which pand it keeps, or why.

The August snapshot also has one pand per VBO, but `ingest.py` deduplicates on `identificatie`,
so it cannot show whether the WFS sent repeats. Of the 37 Delft VBO's whose pand differs between
August and this file, both panden exist in this file's `pand` table every time. Some may be a
different pick of a multi-pand VBO and some real re-links. The file cannot separate them.

Each row has one address: `nummeraanduiding_hoofdadres_identificatie` is the only address link and there is no nevenadres column. `aantal_adressen` in `selectie.py`
counts distinct hoofdadressen of a pand's VBO's, so its meaning does not change.

## Standard library is enough

Every read above ran on stdlib `sqlite3` with no extension loaded. No SpatiaLite and no GIS
library. `ST_MinX` and the like do not exist on this connection and are never needed:

- `ST_*` appear only in the R-tree triggers, which fire on `UPDATE`, never on `SELECT`.
  `gpkg_extensions` marks `gpkg_rtree_index` as `write-only` for all five tables.
- The R-tree tables can be read in this Python build, but the pipeline has no use for them.

## Delft

Filter: `woonplaats_naam = 'Delft'`, one woonplaats (`woonplaats_identificatie` 2138), a full
scan of the table since there is no index.

| Source | Date | VBO's |
| --- | --- | ---: |
| WFS snapshot `vbo_delft.json` | August 2026 | 61.993 |
| This GeoPackage | 2026-11-01 | **61.963** |
| WFS count, given to VA-33 by the squad; not in the project record | 2026-11-06 | 61.965 |

Against August: 61.946 VBO's in both, 47 only in August, 17 only here, net -30. Against the
11-06 WFS: -2. VBO's without a postcode: 1.650 here, 1.649 in August. *Reading:* the differences
are BAG mutations over three months. The 47 and 17 were not traced one by one.

## National figures to keep in view

- VBO's: **9.998.456** here against **9.999.826** from the WFS on 2026-11-06, so 1.370 fewer,
  which fits a file that is five days older (peildatum 2026-11-01). *Corrected 2026-11-08:* this
  line first compared with 9.978.773 and called a 19.683 surplus unexplained, but 9.978.773 is the
  README's August figure (which `PROJECT.md` repeats), not the 11-06 WFS count. Source of
  9.999.826: the handover of 2026-11-08 (`projects/VASTGOED/HANDOFF.md` in the HQ).
- VBO's without a postcode: 416.365 here against 418.223 in the WFS spike. Not explained either.
- **`woonplaats` names are not unique:** 70 names are used by more than one woonplaats (Beek
  three times, Alphen twice). `woonplaats_identificatie` is the safe key. Delft, Rotterdam (3086)
  and `'s-Gravenhage` (1245) are unique. BAG has no woonplaats named "Den Haag".

## Measured read costs

| Read | Time | Peak memory |
| --- | ---: | ---: |
| `COUNT(*)` on `verblijfsobject` | 29 s | not measured |
| `COUNT(*)` on `pand` | 42 s | not measured |
| Full `verblijfsobject` stream, per-row statistics in Python | 882 s | 17 MB |
| Full `pand` stream, per-row statistics in Python | 392 s | 33 MB |
| `GROUP BY identificatie`, both tables, 64 MB page cache | 65 s + 122 s | 149 MB |
| SHA-256 of the file, 1 MB chunks | 84 to 183 s | 17 MB |

Peak memory is the process's peak working set from Windows `GetProcessMemoryInfo`.
