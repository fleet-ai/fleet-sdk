#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "supabase",
#     "aiohttp",
#     "python-dotenv",
# ]
# ///
"""
Remove sessions from session store for DISCARD tasks.
Handles Supabase's 1000 row limit with pagination.

Usage:
    uv run remove_discard_sessions.py [--dry-run]
"""

import argparse
import asyncio
import aiohttp
import os
from dotenv import load_dotenv
from supabase import create_client

# Load environment variables from .env file
load_dotenv()

# === CONFIG ===
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://ehefoavidbttssbleuyv.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")
FLEET_API_BASE = os.environ.get("FLEET_API_BASE", "https://orchestrator.fleetai.com")
FLEET_API_KEY = os.environ.get("FLEET_API_KEY")

STORE_ID = "3fc5edd4-d02c-4f30-be35-ef29c2ec0907"
CONCURRENCY = 50

DISCARD_TASK_KEYS = [
    'task_a5k1j1t6kii_1769860185306_esoo733o7',
    'task_aosvkxtwb3zw_1769892042738_6wanjdiwq',
    'task_bzos2fc9qzem_1769860325328_m1ysp6vvr',
    'task_cr0vw4i1gmk_1769850676296_wy854r081',
    'task_d6zpnuqrde9_1769845911374_lbllb5mk5',
    'task_d8zwctq8augc_1770038670352_amgfoai85',
    'task_deb0jvwbdkpy_1769992026307_m6e0xu2m6',
    'task_dlwcpkjxnemo_n_1770150615434_ncsq9jyso',
    'task_dnhbwjiyq99w_1770061664749_fvmugi2y0',
    'task_ehrotyqnfrpn_1769984036322_cnu3e0kmv',
    'task_etocn2vwyxw_1769944622771_4ot79wy5y',
    'task_fcntij54fes_1769968898959_twi30u22b',
    'task_hrkgkkhsaals_1769856379287_co3jz3kcp',
    'task_ihcs6s8kio1s_n_1770112967873_zxbwx28nx',
    'task_in1qj7j1zzbp_1770049060099_w35r55x7t',
    'task_inl1xwyy3ku6_n_1770077548914_3jatcn8um',
    'task_iocl5zxsommx_1770046837275_gf4x6kkjr',
    'task_ir2ncpokraeg_1770055357969_kofb1hws7',
    'task_irhruye8ed_1769866061092_um182jrbb',
    'task_iwkdovxi5os3_1769878437181_8oveitfv8',
    'task_k4jal6go1tse_1769966263053_6m4v8tkz5',
    'task_kbxzdglxaud1_1770058853521_wffslwacu',
    'task_kirpea4oyt_1769992079368_40y53e97i',
    'task_kkdyjl8imrwa_1769852915482_nmru9l5oz',
    'task_ljxehmepdonf_1770049026416_gzrc8uiqj',
    'task_ltvvisidv2vk_1769997987685_83jln9c8m',
    'task_lujor6kd8pms_1770066698310_ilfhalmgi',
    'task_n2p7deecen_1769966225890_99jij22hm',
    'task_nnodax4vyvvl_1769995688023_cgazunmjh',
    'task_pdge1x9cctbm_1770050922691_nqoizft9n',
    'task_phq9u9kzlsn_1769994475394_r93zwyncw',
    'task_qv1idgrzsmjz_1770037095417_sp0gdz8kw',
    'task_s1zfgfdbnpsa_1769984136494_er29urw6d',
    'task_t0lyqofiv1ya_1770088337324_32a9iogs5',
    'task_ti31bcpqlygj_n_1770134605809_1br9arekb',
    'task_tqrl20m6vq06_1769863884371_mmzwn3wvh',
    'task_tziodb5qdly5_1769983241510_zqzip6jkg',
    'task_umtilk23soa_1770026219571_vu4dmoejn',
    'task_vptw88f02rv_n_1770156014449_4fjcmsvwi',
    'task_w051ik7f2jee_1769943807429_yqd8iei6q',
    'task_w65yc2clg43_1769898061697_k5ypi54h5',
    'task_wax9ux7podr1_1770023833741_f4l8tv0u9',
    'task_y3uqn02ll2l_n_1770119623295_xua5oe72q',
    'task_ycskwaztioky_1770053382916_qnbdp676u',
    'task_zurbpbigk3s_1769873262691_dylj668jz',
    'task_zv7n5vlua7_1769877529754_vcw81sg0y',
    'task_zvqf1f92rz8_1769849020591_ql5t30m2a',
]


def get_all_session_ids_chunked() -> list[str]:
    """
    Fetch all session IDs by iterating through each task.
    This bypasses the 1k limit by querying per-task.
    """
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

    # First, get all task IDs
    print(f"  Looking up {len(DISCARD_TASK_KEYS)} task keys...")
    task_ids = []
    for i, task_key in enumerate(DISCARD_TASK_KEYS, 1):
        task_result = supabase.table("eval_tasks").select("id").eq("key", task_key).execute()
        if task_result.data:
            task_ids.append(task_result.data[0]["id"])
        else:
            print(f"  ⚠️  Task not found: {task_key}")
        
        if i % 10 == 0:
            print(f"  Progress: {i}/{len(DISCARD_TASK_KEYS)} tasks looked up...")

    print(f"  ✓ Found {len(task_ids)}/{len(DISCARD_TASK_KEYS)} tasks in database\n")

    # Get all sessions in the store (paginated)
    print("  Fetching all sessions from store (this may take a moment)...")
    all_store_session_ids = set()
    offset = 0
    page = 0
    while True:
        result = (
            supabase.table("session_stores_sessions")
            .select("session_id")
            .eq("session_store_id", STORE_ID)
            .range(offset, offset + 999)
            .execute()
        )

        if not result.data:
            break

        page += 1
        for r in result.data:
            all_store_session_ids.add(r["session_id"])
        
        print(f"  Page {page}: {len(all_store_session_ids)} sessions loaded so far...")

        if len(result.data) < 1000:
            break
        offset += 1000

    print(f"  ✓ Found {len(all_store_session_ids)} total sessions in store\n")

    # Now filter by task
    print("  Filtering sessions by DISCARD tasks...")
    all_session_ids = set()
    
    for i, task_id in enumerate(task_ids, 1):
        # Get sessions for this task
        offset = 0
        task_count = 0
        while True:
            result = (
                supabase.table("sessions")
                .select("id")
                .eq("eval_task", task_id)
                .range(offset, offset + 999)
                .execute()
            )

            if not result.data:
                break

            for r in result.data:
                session_id = r["id"]
                if session_id in all_store_session_ids:
                    all_session_ids.add(session_id)
                    task_count += 1

            if len(result.data) < 1000:
                break
            offset += 1000

        if task_count > 0:
            print(f"  [{i}/{len(task_ids)}] Task {i}: +{task_count} sessions (total: {len(all_session_ids)})")

    print(f"\n  ✓ Filtering complete!")
    return list(all_session_ids)


async def remove_session(http_session, session_id: str, semaphore, dry_run: bool = False) -> tuple[str, int]:
    """Remove a single session from the store via API."""
    async with semaphore:
        if dry_run:
            # Simulate success in dry-run mode
            await asyncio.sleep(0.01)  # Small delay to simulate API call
            return session_id, 204
        
        url = f"{FLEET_API_BASE}/v1/session-stores/{STORE_ID}/sessions/{session_id}"
        headers = {"Authorization": f"Bearer {FLEET_API_KEY}"}
        try:
            async with http_session.delete(url, headers=headers) as resp:
                return session_id, resp.status
        except Exception as e:
            return session_id, str(e)


async def remove_all_sessions(session_ids: list[str], dry_run: bool = False):
    """Remove all sessions concurrently."""
    semaphore = asyncio.Semaphore(CONCURRENCY)

    mode_str = "DRY RUN - Would remove" if dry_run else "Removing"
    print(f"\n{mode_str} {len(session_ids)} sessions (concurrency: {CONCURRENCY})...")
    print("  Starting removal process...")

    async with aiohttp.ClientSession() as http_session:
        tasks = [remove_session(http_session, sid, semaphore, dry_run) for sid in session_ids]
        
        # Show progress every 100 completions
        results = []
        batch_size = 100
        for i in range(0, len(tasks), batch_size):
            batch = tasks[i:i+batch_size]
            batch_results = await asyncio.gather(*batch)
            results.extend(batch_results)
            print(f"  Progress: {len(results)}/{len(session_ids)} sessions processed...")

    # Summary
    success = sum(1 for _, status in results if status == 204)
    not_found = sum(1 for _, status in results if status == 404)
    errors = [(sid, status) for sid, status in results if status not in (204, 404)]

    print()
    if dry_run:
        print(f"🔍 DRY RUN - Would remove: {success}")
    else:
        print(f"✅ Removed: {success}")
    print(f"⚠️  Not found (already removed?): {not_found}")
    if errors:
        print(f"❌ Errors: {len(errors)}")
        for sid, status in errors[:10]:
            print(f"   {sid}: {status}")


def main():
    parser = argparse.ArgumentParser(description="Remove sessions from session store for DISCARD tasks")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be removed without actually removing")
    args = parser.parse_args()

    if not SUPABASE_KEY:
        print("ERROR: Set SUPABASE_SERVICE_KEY env var")
        print("  export SUPABASE_SERVICE_KEY='your-service-key'")
        return
    if not FLEET_API_KEY and not args.dry_run:
        print("ERROR: Set FLEET_API_KEY env var")
        print("  export FLEET_API_KEY='your-api-key'")
        return

    if args.dry_run:
        print("🔍 DRY RUN MODE - No sessions will be removed\n")

    print(f"Store ID: {STORE_ID}")
    print(f"Tasks to process: {len(DISCARD_TASK_KEYS)}")
    print()

    print("Step 1: Fetching session IDs from Supabase...")
    session_ids = get_all_session_ids_chunked()
    print(f"\nFound {len(session_ids)} sessions to remove")

    if not session_ids:
        print("No sessions found!")
        return

    # Save to CSV for backup
    csv_path = "sessions_to_remove.csv"
    with open(csv_path, "w") as f:
        f.write("session_id\n")
        for sid in session_ids:
            f.write(f"{sid}\n")
    print(f"Saved to {csv_path}")

    if args.dry_run:
        print("\n🔍 DRY RUN - Simulating removal...")
        asyncio.run(remove_all_sessions(session_ids, dry_run=True))
        print("\nDry run complete! Run without --dry-run to actually remove sessions.")
        return

    # Confirm before proceeding
    confirm = input(f"\nProceed to remove {len(session_ids)} sessions? [y/N] ")
    if confirm.lower() != 'y':
        print("Aborted. You can re-run with the CSV later.")
        return

    print("\nStep 2: Removing sessions via API...")
    asyncio.run(remove_all_sessions(session_ids, dry_run=False))
    print("\nDone!")


if __name__ == "__main__":
    main()
