import fleet

account = fleet.env.account()

print(f"Team ID: {account.team_id}")
print(f"Team Name: {account.team_name}")
print(f"Instance Limit: {account.instance_limit}")
print(f"Instance Count: {account.instance_count}")
