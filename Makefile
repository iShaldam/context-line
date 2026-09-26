.PHONY: check test selftest validate leakscan

check: validate test selftest

validate:
	claude plugin validate --strict .

test:
	python3 -m unittest discover -s tests

selftest:
	bash scripts/selftest.sh
	bash scripts/leakscan.sh --selftest

leakscan:
	bash scripts/leakscan.sh
