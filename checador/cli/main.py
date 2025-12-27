"""CLI commands for Checador."""

import argparse
import asyncio
import csv
import sys
from datetime import datetime
from pathlib import Path

from checador.camera import CameraManager
from checador.config import Config
from checador.database import Database
from checador.sync import SyncWorker


def export_punches(args):
    """Export punches to CSV."""
    async def _export():
        config = Config(args.config)
        db = Database(config.database_path)
        await db.initialize()
        
        # Parse dates
        start_date = datetime.fromisoformat(args.start) if args.start else None
        end_date = datetime.fromisoformat(args.end) if args.end else None
        
        # Get punches
        punches = await db.get_punches(start_date=start_date, end_date=end_date)
        
        # Write CSV
        output_path = Path(args.output)
        with open(output_path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                'Punch ID', 'Employee Code', 'Name', 'Timestamp Local',
                'Timestamp UTC', 'Type', 'Match Score', 'Device ID', 'Synced'
            ])
            
            for punch in punches:
                user = await db.get_user(punch.user_id)
                writer.writerow([
                    punch.id,
                    user.employee_code if user else '',
                    user.name if user else '',
                    punch.timestamp_local.isoformat(),
                    punch.timestamp_utc.isoformat(),
                    punch.punch_type,
                    punch.match_score,
                    punch.device_id,
                    'Yes' if punch.synced else 'No'
                ])
        
        print(f"Exported {len(punches)} punches to {output_path}")
    
    asyncio.run(_export())


def list_users(args):
    """List all users."""
    async def _list():
        config = Config(args.config)
        db = Database(config.database_path)
        await db.initialize()
        
        users = await db.list_users(active_only=not args.all)
        
        print(f"\n{'ID':<6} {'Code':<15} {'Name':<30} {'Active':<8} {'Templates':<10}")
        print("-" * 75)
        
        for user in users:
            templates = await db.get_user_templates(user.id)
            print(f"{user.id:<6} {user.employee_code:<15} {user.name:<30} "
                  f"{'Yes' if user.active else 'No':<8} {len(templates):<10}")
        
        print(f"\nTotal: {len(users)} users")
    
    asyncio.run(_list())


def deactivate_user(args):
    """Deactivate a user."""
    async def _deactivate():
        config = Config(args.config)
        db = Database(config.database_path)
        await db.initialize()
        
        user = await db.get_user_by_code(args.employee_code)
        if not user:
            print(f"User not found: {args.employee_code}")
            return
        
        await db.deactivate_user(user.id)
        print(f"User deactivated: {user.name} ({user.employee_code})")
    
    asyncio.run(_deactivate())


def test_camera(args):
    """Test camera."""
    config = Config(args.config)
    camera = CameraManager(config)
    
    print("Testing camera...")
    result = camera.test_camera()
    
    print(f"\nCamera Test Results:")
    print(f"  Device: {result['device']}")
    print(f"  Accessible: {'Yes' if result['accessible'] else 'No'}")
    print(f"  Opened: {'Yes' if result['opened'] else 'No'}")
    print(f"  Frame Captured: {'Yes' if result['frame_captured'] else 'No'}")
    print(f"  Resolution: {result['resolution'] or 'N/A'}")
    print(f"  ROI Valid: {'Yes' if result['roi_valid'] else 'No'}")
    
    if result['error']:
        print(f"  Error: {result['error']}")
    
    if result['frame_captured'] and result['roi_valid']:
        print("\n✓ Camera is working correctly")
    else:
        print("\n✗ Camera issues detected")


def sync_now(args):
    """Trigger sync now."""
    async def _sync():
        config = Config(args.config)
        db = Database(config.database_path)
        await db.initialize()
        
        sync_worker = SyncWorker(config, db)
        
        print("Syncing punches...")
        success = await sync_worker.sync_now()
        
        if success:
            print("✓ Sync completed successfully")
        else:
            print("✗ Sync failed")
    
    asyncio.run(_sync())


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Checador CLI")
    parser.add_argument(
        '--config',
        default='/etc/checador/config.toml',
        help='Config file path'
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Command')
    
    # Export command
    export_parser = subparsers.add_parser('export', help='Export punches to CSV')
    export_parser.add_argument('--output', required=True, help='Output CSV file')
    export_parser.add_argument('--start', help='Start date (ISO format)')
    export_parser.add_argument('--end', help='End date (ISO format)')
    
    # Users command
    users_parser = subparsers.add_parser('users', help='User management')
    users_subparsers = users_parser.add_subparsers(dest='users_command')
    
    list_parser = users_subparsers.add_parser('list', help='List users')
    list_parser.add_argument('--all', action='store_true', help='Include inactive users')
    
    deactivate_parser = users_subparsers.add_parser('deactivate', help='Deactivate user')
    deactivate_parser.add_argument('--employee-code', required=True, help='Employee code')
    
    # Camera command
    camera_parser = subparsers.add_parser('camera', help='Camera utilities')
    camera_subparsers = camera_parser.add_subparsers(dest='camera_command')
    camera_subparsers.add_parser('test', help='Test camera')
    
    # Sync command
    sync_parser = subparsers.add_parser('sync', help='Sync utilities')
    sync_subparsers = sync_parser.add_subparsers(dest='sync_command')
    sync_subparsers.add_parser('now', help='Trigger sync now')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    # Route commands
    try:
        if args.command == 'export':
            export_punches(args)
        elif args.command == 'users':
            if args.users_command == 'list':
                list_users(args)
            elif args.users_command == 'deactivate':
                deactivate_user(args)
        elif args.command == 'camera':
            if args.camera_command == 'test':
                test_camera(args)
        elif args.command == 'sync':
            if args.sync_command == 'now':
                sync_now(args)
    except KeyboardInterrupt:
        print("\nInterrupted")
        sys.exit(130)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()