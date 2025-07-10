"""
Nova Act + Fleet SDK Eval Example with JSON Tasks

This example demonstrates how to:
1. Load evaluation tasks from JSON format
2. Use Nova Act for browser automation with Fleet's Fira environment
3. Execute verifier functions to validate task completion
4. Show how to use "a task from json" as requested

Requirements:
- pip install fleet-python nova-act
- export FLEET_API_KEY="your-fleet-api-key"
- export NOVA_ACT_API_KEY="your-nova-act-api-key"

Usage:
    python nova_act_eval_example.py
"""

import json
import os
import sys
from typing import Dict, Any, List
from concurrent.futures import ThreadPoolExecutor
import fleet as flt
from fleet.verifiers import DatabaseSnapshot, IgnoreConfig, TASK_SUCCESSFUL_SCORE
import nova_act


# Load tasks from JSON file
def load_tasks_from_json(json_path: str) -> List[Dict[str, Any]]:
    """Load evaluation tasks from JSON file."""
    try:
        with open(json_path, 'r') as f:
            data = json.load(f)
        return data.get('problems', [])
    except FileNotFoundError:
        print(f"❌ JSON file not found: {json_path}")
        return []
    except json.JSONDecodeError as e:
        print(f"❌ Invalid JSON in file {json_path}: {e}")
        return []


def create_verifier_function(verifier_code: str):
    """Create a verifier function from Python code string."""
    # The verifier code is a complete function definition
    # We need to execute it to create the function
    local_scope = {
        'DatabaseSnapshot': DatabaseSnapshot,
        'IgnoreConfig': IgnoreConfig,
        'TASK_SUCCESSFUL_SCORE': TASK_SUCCESSFUL_SCORE
    }
    
    exec(verifier_code, local_scope, local_scope)
    
    # Find the function in the local scope
    for name, obj in local_scope.items():
        if callable(obj) and name.startswith('validate_'):
            return obj
    
    raise ValueError("No verifier function found in provided code")


def run_nova_act_task(fleet_app_url: str, task_description: str) -> Dict[str, Any]:
    """Run a Nova Act task with the given description."""
    print(f"\n🤖 Starting Nova Act task: {task_description}")
    
    results = {
        "success": False,
        "error": None,
        "actions_taken": []
    }
    
    try:
        with nova_act.NovaAct(
            headless=False,  # Set to True for headless mode
            starting_page=fleet_app_url
        ) as nova:
            print("✅ Nova Act connected successfully!")
            
            # Give Nova Act the task
            result = nova.act(
                f"I need to complete this task: {task_description}. "
                f"Please analyze the current page and take the necessary actions to complete this task."
            )
            
            results["actions_taken"].append({
                "action": "initial_analysis",
                "result": result.response if hasattr(result, 'response') else str(result)
            })
            
            # For the first task (give-me-more-tasks), we need to:
            # 1. Navigate to the project management interface
            # 2. Find bugs in the engineering project
            # 3. Move them to sprint 3
            # 4. Assign data pipeline bug to Sarah Kim (me)
            # 5. Assign other bugs to Raj Patel
            
            if "move all the bugs to sprint 3" in task_description.lower():
                print("🔧 Handling bug assignment and sprint management task...")
                
                # Navigate to the project view
                result = nova.act("Navigate to the main project or issues view where I can see all the bugs")
                results["actions_taken"].append({
                    "action": "navigate_to_project",
                    "result": result.response if hasattr(result, 'response') else str(result)
                })
                
                # Find and filter bugs
                result = nova.act("Filter or search for all bugs in the engineering project")
                results["actions_taken"].append({
                    "action": "filter_bugs",
                    "result": result.response if hasattr(result, 'response') else str(result)
                })
                
                # Move bugs to sprint 3
                result = nova.act("Move all the bugs to sprint 3")
                results["actions_taken"].append({
                    "action": "move_to_sprint_3",
                    "result": result.response if hasattr(result, 'response') else str(result)
                })
                
                # Assign data pipeline bug to Sarah Kim
                result = nova.act("Find the data pipeline bug and assign it to Sarah Kim (me)")
                results["actions_taken"].append({
                    "action": "assign_data_pipeline_bug",
                    "result": result.response if hasattr(result, 'response') else str(result)
                })
                
                # Assign other bugs to Raj Patel
                result = nova.act("Assign all the other bugs to Raj Patel")
                results["actions_taken"].append({
                    "action": "assign_other_bugs_to_raj",
                    "result": result.response if hasattr(result, 'response') else str(result)
                })
                
            elif "exponential story points" in task_description.lower():
                print("🔧 Handling exponential story points conversion task...")
                
                # Navigate to issues assigned to Sarah Kim
                result = nova.act("Navigate to issues assigned to Sarah Kim and filter for platform eng project")
                results["actions_taken"].append({
                    "action": "navigate_to_sarah_issues",
                    "result": result.response if hasattr(result, 'response') else str(result)
                })
                
                # Convert story points to exponential values
                result = nova.act(
                    "Convert all story points to exponential values (1, 2, 4, 8, 16, etc.), "
                    "rounding up when equidistant. Focus on active, planned, and backlogged issues."
                )
                results["actions_taken"].append({
                    "action": "convert_story_points",
                    "result": result.response if hasattr(result, 'response') else str(result)
                })
            
            results["success"] = True
            print("✅ Nova Act task completed successfully!")
            
    except Exception as e:
        print(f"❌ Error during Nova Act task: {type(e).__name__}: {str(e)}")
        results["error"] = str(e)
        import traceback
        traceback.print_exc()
    
    return results


def run_evaluation_task(env, task: Dict[str, Any]) -> Dict[str, Any]:
    """Run a complete evaluation task: Nova Act + Verifier."""
    print(f"\n{'='*60}")
    print(f"🎯 Running Task: {task['id']}")
    print(f"📝 Description: {task['problem']}")
    print(f"📊 Category: {task['category']}")
    print(f"🎚️ Difficulty: {task['difficulty']}")
    print(f"{'='*60}")
    
    results = {
        "task_id": task['id'],
        "success": False,
        "nova_act_results": None,
        "verifier_results": None,
        "error": None
    }
    
    try:
        # Take a snapshot before the task
        print("📸 Taking before snapshot...")
        db = env.db()
        before_snapshot = db.snapshot()
        
        # Run Nova Act task in a separate thread
        print("🚀 Running Nova Act automation...")
        with ThreadPoolExecutor() as executor:
            nova_future = executor.submit(
                run_nova_act_task,
                env.urls.app,
                task['problem']
            )
            nova_act_results = nova_future.result()
        
        results["nova_act_results"] = nova_act_results
        
        if not nova_act_results["success"]:
            results["error"] = f"Nova Act failed: {nova_act_results['error']}"
            return results
        
        # Take a snapshot after the task
        print("📸 Taking after snapshot...")
        after_snapshot = db.snapshot()
        
        # Create and run verifier function
        print("🔍 Running verification...")
        verifier_func = create_verifier_function(task['verifier_func'])
        
        try:
            score = verifier_func(before_snapshot, after_snapshot)
            
            results["verifier_results"] = {
                "success": True,
                "score": score,
                "passed": score == TASK_SUCCESSFUL_SCORE,
                "error": None
            }
            
            if score == TASK_SUCCESSFUL_SCORE:
                print(f"✅ Task '{task['id']}' PASSED! Score: {score}")
                results["success"] = True
            else:
                print(f"❌ Task '{task['id']}' FAILED. Score: {score}")
                
        except Exception as verifier_error:
            print(f"❌ Verifier error: {str(verifier_error)}")
            results["verifier_results"] = {
                "success": False,
                "score": 0,
                "passed": False,
                "error": str(verifier_error)
            }
            
    except Exception as e:
        print(f"❌ Task execution error: {str(e)}")
        results["error"] = str(e)
        import traceback
        traceback.print_exc()
    
    return results


def main():
    """Main function to run evaluation tasks."""
    print("🚀 Starting Nova Act + Fleet SDK Evaluation")
    print("=" * 60)
    
    # Check for required API keys
    if not os.getenv("FLEET_API_KEY"):
        print("❌ FLEET_API_KEY environment variable not set!")
        return
    
    if not os.getenv("NOVA_ACT_API_KEY"):
        print("❌ NOVA_ACT_API_KEY environment variable not set!")
        return
    
    # Load tasks from JSON
    json_path = "eval_tasks.json"
    if len(sys.argv) > 1:
        json_path = sys.argv[1]
    
    tasks = load_tasks_from_json(json_path)
    if not tasks:
        print(f"❌ No tasks found in {json_path}")
        return
    
    print(f"📋 Loaded {len(tasks)} tasks from {json_path}")
    
    # Initialize Fleet environment
    print("\n🌍 Setting up Fleet environment...")
    try:
        env = flt.env.make("fira")  # Using Fira environment
        print(f"✅ Environment created: {env.instance_id}")
        
        # Reset environment to clean state
        print("🔄 Resetting environment...")
        reset_result = env.reset(seed=42)
        print(f"✅ Reset complete: {reset_result}")
        
        # Run each task
        all_results = []
        for i, task in enumerate(tasks, 1):
            print(f"\n🎯 Task {i}/{len(tasks)}: {task['id']}")
            
            task_results = run_evaluation_task(env, task)
            all_results.append(task_results)
            
            # Summary for this task
            status = "✅ PASSED" if task_results["success"] else "❌ FAILED"
            print(f"📊 Task Result: {status}")
        
        # Final summary
        print("\n" + "=" * 60)
        print("📊 EVALUATION SUMMARY")
        print("=" * 60)
        
        passed_count = sum(1 for r in all_results if r["success"])
        total_count = len(all_results)
        
        print(f"✅ Passed: {passed_count}/{total_count}")
        print(f"❌ Failed: {total_count - passed_count}/{total_count}")
        print(f"📈 Success Rate: {passed_count/total_count*100:.1f}%")
        
        # Detailed results
        print("\n📋 Detailed Results:")
        for result in all_results:
            status = "✅ PASS" if result["success"] else "❌ FAIL"
            print(f"  {result['task_id']}: {status}")
            if result.get("error"):
                print(f"    Error: {result['error']}")
        
        # Cleanup
        print("\n🧹 Cleaning up...")
        env.close()
        print("✅ Environment cleaned up")
        
    except Exception as e:
        print(f"❌ Setup error: {str(e)}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n⚠️ Evaluation interrupted by user")
    except Exception as e:
        print(f"\n❌ Unexpected error: {str(e)}")
        import traceback
        traceback.print_exc() 