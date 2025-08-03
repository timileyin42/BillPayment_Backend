#!/usr/bin/env python3
"""
Test runner script for Vision Fintech Backend.

This script provides various options for running tests:
- Run all tests
- Run specific test categories (unit, integration, api)
- Run tests for specific modules (wallet, payment, cashback)
- Generate coverage reports
- Run tests with different verbosity levels

Usage:
    python run_tests.py                    # Run all tests
    python run_tests.py --unit             # Run only unit tests
    python run_tests.py --wallet           # Run only wallet tests
    python run_tests.py --coverage         # Run with coverage report
    python run_tests.py --verbose          # Run with verbose output
"""

import argparse
import subprocess
import sys
import os
from pathlib import Path


def run_command(cmd, description=""):
    """Run a command and handle errors."""
    if description:
        print(f"\n{description}")
        print("=" * len(description))
    
    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.stdout:
        print(result.stdout)
    
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    
    if result.returncode != 0:
        print(f"Command failed with exit code {result.returncode}")
        sys.exit(result.returncode)
    
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Test runner for Vision Fintech Backend",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run_tests.py                     # Run all tests
  python run_tests.py --unit              # Run only unit tests
  python run_tests.py --integration       # Run only integration tests
  python run_tests.py --api               # Run only API tests
  python run_tests.py --wallet            # Run only wallet-related tests
  python run_tests.py --payment           # Run only payment-related tests
  python run_tests.py --cashback          # Run only cashback-related tests
  python run_tests.py --auth              # Run only auth-related tests
  python run_tests.py --biller            # Run only biller-related tests
  python run_tests.py --coverage          # Run with coverage report
  python run_tests.py --coverage --html   # Generate HTML coverage report
  python run_tests.py --verbose           # Run with verbose output
  python run_tests.py --fast              # Skip slow tests
  python run_tests.py --file test_wallet_service.py  # Run specific test file
        """
    )
    
    # Test category options
    parser.add_argument('--unit', action='store_true', help='Run only unit tests')
    parser.add_argument('--integration', action='store_true', help='Run only integration tests')
    parser.add_argument('--api', action='store_true', help='Run only API tests')
    
    # Module-specific options
    parser.add_argument('--wallet', action='store_true', help='Run only wallet tests')
    parser.add_argument('--payment', action='store_true', help='Run only payment tests')
    parser.add_argument('--cashback', action='store_true', help='Run only cashback tests')
    parser.add_argument('--auth', action='store_true', help='Run only auth tests')
    parser.add_argument('--biller', action='store_true', help='Run only biller tests')
    
    # Coverage options
    parser.add_argument('--coverage', action='store_true', help='Run with coverage report')
    parser.add_argument('--html', action='store_true', help='Generate HTML coverage report (requires --coverage)')
    
    # Output options
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
    parser.add_argument('--quiet', '-q', action='store_true', help='Quiet output')
    
    # Performance options
    parser.add_argument('--fast', action='store_true', help='Skip slow tests')
    parser.add_argument('--parallel', '-n', type=int, help='Run tests in parallel (number of workers)')
    
    # Specific test options
    parser.add_argument('--file', help='Run specific test file')
    parser.add_argument('--test', help='Run specific test function')
    
    # Additional pytest options
    parser.add_argument('--failfast', '-x', action='store_true', help='Stop on first failure')
    parser.add_argument('--pdb', action='store_true', help='Drop into debugger on failures')
    
    args = parser.parse_args()
    
    # Ensure we're in the project root
    project_root = Path(__file__).parent
    os.chdir(project_root)
    
    # Build pytest command
    cmd = ['python', '-m', 'pytest']
    
    # Add markers based on arguments
    markers = []
    
    if args.unit:
        markers.append('unit')
    if args.integration:
        markers.append('integration')
    if args.api:
        markers.append('api')
    if args.wallet:
        markers.append('wallet')
    if args.payment:
        markers.append('payment')
    if args.cashback:
        markers.append('cashback')
    if args.auth:
        markers.append('auth')
    if args.biller:
        markers.append('biller')
    
    if markers:
        cmd.extend(['-m', ' or '.join(markers)])
    
    # Add coverage options
    if args.coverage:
        cmd.extend(['--cov=app', '--cov-report=term-missing'])
        if args.html:
            cmd.append('--cov-report=html')
    
    # Add verbosity options
    if args.verbose:
        cmd.append('-v')
    elif args.quiet:
        cmd.append('-q')
    
    # Add performance options
    if args.fast:
        cmd.extend(['-m', 'not slow'])
    
    if args.parallel:
        cmd.extend(['-n', str(args.parallel)])
    
    # Add specific test options
    if args.file:
        cmd.append(f'tests/{args.file}' if not args.file.startswith('tests/') else args.file)
    
    if args.test:
        cmd.extend(['-k', args.test])
    
    # Add additional options
    if args.failfast:
        cmd.append('-x')
    
    if args.pdb:
        cmd.append('--pdb')
    
    # If no specific tests specified, run all tests
    if not any([args.unit, args.integration, args.api, args.wallet, args.payment, 
                args.cashback, args.auth, args.biller, args.file, args.test]):
        cmd.append('tests/')
    
    # Run the tests
    try:
        print("Vision Fintech Backend - Test Runner")
        print("====================================\n")
        
        # Check if pytest is installed
        try:
            subprocess.run(['python', '-m', 'pytest', '--version'], 
                         capture_output=True, check=True)
        except subprocess.CalledProcessError:
            print("Error: pytest is not installed. Please install it with:")
            print("pip install pytest pytest-asyncio pytest-cov")
            sys.exit(1)
        
        # Run the tests
        result = run_command(cmd, "Running Tests")
        
        # If coverage was requested and HTML report generated, show location
        if args.coverage and args.html:
            html_report = project_root / 'htmlcov' / 'index.html'
            if html_report.exists():
                print(f"\nHTML coverage report generated: {html_report}")
                print("Open this file in your browser to view the detailed coverage report.")
        
        print("\n All tests completed successfully!")
        
    except KeyboardInterrupt:
        print("\n Tests interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n Error running tests: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()