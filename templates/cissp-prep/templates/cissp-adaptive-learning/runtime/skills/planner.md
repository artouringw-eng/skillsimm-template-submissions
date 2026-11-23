# Adaptive study planner

Given a weak domain and allowed_dates, return {"date":"YYYY-MM-DD",
"reason":"why this 20-minute review is useful and how to use it"}.
Choose exactly one of allowed_dates, normally the earliest. Recommend a targeted
retrieval/practice activity for that domain. Never remove or replace calendar topics,
change the exam deadline, schedule outside allowed_dates, or change the 20-minute
duration. The coordinator enforces the minimum five attempts and below-70% rule,
available daily time and exam deadline. Do not reinterpret those thresholds.
