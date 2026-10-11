#!/usr/bin/env python
"""Add slug column to items table and backfill slugs for existing items."""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from digest import db


def slugify(title: str) -> str:
    """Convert title to URL-safe slug."""
    if not title:
        return "untitled"
    slug = re.sub(r"[^\w\s-]", "", title).lower()
    slug = re.sub(r"[-\s]+", "-", slug).strip("-")
    return slug[:50]  # limit length


def main():
    try:
        with db.connect() as conn:
            # Add slug column if it doesn't exist
            try:
                conn.execute("ALTER TABLE items ADD COLUMN slug TEXT")
                print("✓ Added slug column")
            except Exception as e:
                if "already exists" in str(e).lower():
                    print("  slug column already exists")
                else:
                    raise

            # Get items without slugs
            rows = conn.execute(
                "SELECT id, title FROM items WHERE slug IS NULL ORDER BY id"
            ).fetchall()
            
            if not rows:
                print("✓ All items already have slugs")
                return 0
            
            print(f"Generating slugs for {len(rows)} items...")
            seen_slugs = set()
            
            for row in rows:
                item_id = row["id"]
                base_slug = slugify(row["title"] or f"item-{item_id}")
                
                # Ensure uniqueness
                slug = base_slug
                counter = 1
                while slug in seen_slugs:
                    slug = f"{base_slug}-{counter}"
                    counter += 1
                seen_slugs.add(slug)
                
                conn.execute("UPDATE items SET slug = %s WHERE id = %s", (slug, item_id))
            
            conn.commit()
            print(f"✓ Generated {len(rows)} slugs")
            
            # Add unique constraint
            try:
                conn.execute("ALTER TABLE items ADD CONSTRAINT items_slug_key UNIQUE (slug)")
                print("✓ Added unique constraint on slug")
            except Exception as e:
                if "already exists" in str(e).lower():
                    print("  unique constraint already exists")
                else:
                    raise
            
            return 0
    except db.DatabaseProblem as e:
        print(f"✗ {e}")
        return 1
    except Exception as e:
        import traceback
        print(f"✗ Error: {e}")
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
