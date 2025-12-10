# from django.test import TestCase
# from django.contrib.auth.models import User
# from rest_framework.test import APIClient
# from .models import MENTUser

# class MENTPermissionsTest(TestCase):
#     def setUp(self):
#         self.admin_django_user = User.objects.create(username="admin_user")
#         self.regular_django_user = User.objects.create(username="regular_user")

#         MENTUser.objects.create(external_user_id=self.admin_django_user.id, role="admin")
#         MENTUser.objects.create(external_user_id=self.regular_django_user.id, role="regular")

#         self.client = APIClient()

#     def test_admin_access(self):
#         """Admin should have access creating file association"""
#         self.client.force_authenticate(user=self.admin_django_user)
#         response = self.client.post('/ttscanner/file-associations/create/', {
#             "algo_name": "TTScanner",
#             "group_name": "SPDR",
#             "interval_name": "5min"
#         }, format='json')
#         print("Admin status code:", response.status_code)
#         self.assertEqual(response.status_code, 201) 

#     def test_regular_access(self):
#         """Regular user should be forbidden from creating file association"""
#         self.client.force_authenticate(user=self.regular_django_user)
#         response = self.client.post('/ttscanner/file-associations/create/', {
#             "algo_name": "TTScanner",
#             "group_name": "SPDR",
#             "interval_name": "5min"
#         }, format='json')
#         print("Regular user status code:", response.status_code)
#         self.assertEqual(response.status_code, 403) 



# test_alerts.py
# from ttscanner.models import FileAssociation, SymbolState
# import ttscanner.engine.evaluator as ev
# from unittest.mock import patch

# print("=== ALERT SYSTEM FULL TEST START ===\n")

# files = FileAssociation.objects.all()
# if not files:
#     raise Exception("No FileAssociation found. Add some test files first.")

# print(f"[INFO] {files.count()} FileAssociation instances found.\n")

# with patch("ttscanner.utils.email_utils.send_alert_email") as mock_email, \
#      patch("ttscanner.utils.sms_utils.send_alert_sms") as mock_sms:

#     mock_email.side_effect = lambda *a, **k: print(f"[MOCK EMAIL] to {a[0]} | subject: {a[1]}")
#     mock_sms.side_effect = lambda *a, **k: print(f"[MOCK SMS] to {a[0]} | message: {a[1]}")

#     for fa in files:
#         algo = getattr(fa, "algo", None)
#         if not algo:
#             print(f"[SKIP] {fa.file_name} → no algo associated")
#             continue

#         print(f"\n=== TESTING FILE: {fa.file_name} | Algo: {algo.algo_name} ===")

#         test_rows = [
#             {"Symbol": "TEST1", "Last": 100, "Target #1": 105, "Target #2": 110, "Direction": "long", "Profit %": 1},
#             {"Symbol": "TEST1", "Last": 106, "Target #1": 105, "Target #2": 110, "Direction": "long", "Profit %": 6},
#             {"Symbol": "TEST1", "Last": 111, "Target #1": 105, "Target #2": 110, "Direction": "long", "Profit %": 11},
#             {"Symbol": "TEST1", "Last": 108, "Target #1": 105, "Target #2": 110, "Direction": "short", "Profit %": 8},
#         ]

#         for idx, row in enumerate(test_rows, start=1):
#             print(f"\n[ROW {idx}] Processing row: {row}")
#             alerts = ev.process_row_for_alerts(fa, algo, row)

#             if alerts:
#                 print(f"[ROW {idx}] {len(alerts)} alerts triggered:")
#                 for a in alerts:
#                     print("  ALERT:", a.message)
#             else:
#                 print(f"[ROW {idx}] No alerts triggered.")

#         symbols = set(row['Symbol'] for row in test_rows)
#         for sym in symbols:
#             try:
#                 state = SymbolState.objects.get(file_association=fa, symbol=sym)
#                 print(f"\n=== SYMBOL STATE for {sym} in {fa.file_name} ===")
#                 print("Last row data:", state.last_row_data)
#                 print("Last price:", state.last_price)
#                 print("Last direction:", state.last_direction)
#                 print("Target1 hit:", state.target1_hit)
#                 print("Target2 hit:", state.target2_hit)
#                 print("Last alerts:", state.last_alerts)
#             except SymbolState.DoesNotExist:
#                 print(f"No SymbolState found for {fa.file_name}, symbol {sym}")

# print("\n=== ALERT SYSTEM FULL TEST END ===")


from ttscanner.models import FileAssociation
from ttscanner.engine.evaluator import process_row_for_alerts

def run_mentfib_test():
    print("=== MENTFib TEST START ===\n")
    
    # Deduplicate files by name
    processed_files = set()
    fa_qs = FileAssociation.objects.filter(file_name__icontains="MENTFib")
    
    # Sample MENTFib rows
    mentfib_rows = [
        {"Symbol/Interval":"IGM 10", "Last Price":131.68, "Fib Pivot Trend":"BULLISH", "Fib Price Range Trend":"Normal Range",
         "Bull Fib Trigger Level":131.42,"Bull Zone 1":131.55,"Bull Zone 2":132.83,"Bull Zone 3":130.3,
         "Bear Fib Trigger Level":131.92,"Bear Zone 1":131.4,"Bear Zone 2":130.3,"Bear Zone 3":130.57},
        {"Symbol/Interval":"QID 10", "Last Price":20.02, "Fib Pivot Trend":"BULLISH", "Fib Price Range Trend":"Contraction",
         "Bull Fib Trigger Level":20.25,"Bull Zone 1":19.95,"Bull Zone 2":20.35,"Bull Zone 3":19.7,
         "Bear Fib Trigger Level":20.13,"Bear Zone 1":20.0,"Bear Zone 2":19.7,"Bear Zone 3":19.75},
        {"Symbol/Interval":"IYC 10", "Last Price":102.96, "Fib Pivot Trend":"BEARISH", "Fib Price Range Trend":"Expansion",
         "Bull Fib Trigger Level":102.8,"Bull Zone 1":102.94,"Bull Zone 2":103.33,"Bull Zone 3":102.16,
         "Bear Fib Trigger Level":103.09,"Bear Zone 1":102.04,"Bear Zone 2":102.16,"Bear Zone 3":101.62},
        {"Symbol/Interval":"KBE 10", "Last Price":60.34, "Fib Pivot Trend":"BULLISH", "Fib Price Range Trend":"Normal Range",
         "Bull Fib Trigger Level":60.47,"Bull Zone 1":60.57,"Bull Zone 2":61.19,"Bull Zone 3":59.8,
         "Bear Fib Trigger Level":60.77,"Bear Zone 1":60.48,"Bear Zone 2":59.8,"Bear Zone 3":60.01},
        {"Symbol/Interval":"ETHA 10", "Last Price":23.76, "Fib Pivot Trend":"BULLISH", "Fib Price Range Trend":"Expansion",
         "Bull Fib Trigger Level":23.52,"Bull Zone 1":23.55,"Bull Zone 2":24.7,"Bull Zone 3":22.71,
         "Bear Fib Trigger Level":23.43,"Bear Zone 1":22.92,"Bear Zone 2":22.71,"Bear Zone 3":22.44},
        {"Symbol/Interval":"FBTC 10", "Last Price":80.64, "Fib Pivot Trend":"BEARISH", "Fib Price Range Trend":"Normal Range",
         "Bull Fib Trigger Level":79.81,"Bull Zone 1":79.9,"Bull Zone 2":82.23,"Bull Zone 3":78.05,
         "Bear Fib Trigger Level":79.96,"Bear Zone 1":78.93,"Bear Zone 2":78.05,"Bear Zone 3":77.74},
        {"Symbol/Interval":"IXC 10", "Last Price":43.56, "Fib Pivot Trend":"BULLISH", "Fib Price Range Trend":"Normal Range",
         "Bull Fib Trigger Level":43.59,"Bull Zone 1":43.48,"Bull Zone 2":43.92,"Bull Zone 3":42.78,
         "Bear Fib Trigger Level":43.98,"Bear Zone 1":43.44,"Bear Zone 2":42.78,"Bear Zone 3":42.97},
        {"Symbol/Interval":"JETS 10", "Last Price":26.95, "Fib Pivot Trend":"BULLISH", "Fib Price Range Trend":"Contraction",
         "Bull Fib Trigger Level":27.36,"Bull Zone 1":26.81,"Bull Zone 2":27.59,"Bull Zone 3":26.77,
         "Bear Fib Trigger Level":27.15,"Bear Zone 1":26.59,"Bear Zone 2":26.77,"Bear Zone 3":26.49},
    ]

    for fa in fa_qs:
        if fa.file_name in processed_files:
            continue
        processed_files.add(fa.file_name)

        print(f"[TEST] Running MENTFib test for: {fa.file_name}")
        
        algo = fa.algo 
        if not algo:
            print(f"[TEST] No algo set for {fa.file_name}. Skipping.")
            continue

        total_alerts = 0
        for row in mentfib_rows:
            print(row)
            alerts = process_row_for_alerts(fa, algo, row)
            for alert in alerts:
                print(f"[ALERT] {alert.message}")
            total_alerts += len(alerts)

        print(f"[TEST] Total {total_alerts} alerts triggered.\n")

    print("=== MENTFib TEST END ===\n")

# Run the test
run_mentfib_test()



# import json
# from ttscanner.models import FileAssociation, TriggeredAlert
# from ttscanner.engine.evaluator import process_row_for_alerts

# def run_fsoptions_test():
#     print("\n=== FSOptions TEST START ===\n")
    
#     # Fetch FSOptions files
#     fs_files = FileAssociation.objects.filter(algo__algo_name="FSOptions")
#     if not fs_files.exists():
#         print("[TEST] No FSOptions files found.")
#         return

#     for fa in fs_files:
#         print(f"[TEST] Running FSOptions test for: {fa.file_name}")
        
#         main_data = fa.maindata.first()
#         if not main_data:
#             print(f"[TEST] No main data found for {fa.file_name}")
#             continue

#         rows = main_data.data_json.get("rows", [])
#         if not rows:
#             print(f"[TEST] No rows found for {fa.file_name}")
#             continue

#         algo = fa.algo
#         total_alerts = 0

#         for row_index, row in enumerate(rows):
#             print(f"\n[ROW {row_index+1}] Processing: {row}")
#             triggered_alerts = process_row_for_alerts(fa, algo, row)
            
#             for alert in triggered_alerts:
#                 print(f"[ALERT] {alert.message}")
#             total_alerts += len(triggered_alerts)

#         print(f"\n[TEST] Total {total_alerts} alerts triggered for {fa.file_name}\n")

#     print("\n=== FSOptions TEST END ===\n")

# # Run the test
# run_fsoptions_test()
