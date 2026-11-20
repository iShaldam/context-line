.PHONY: check release test selftest validate leakscan

check: validate test selftest release

validate:
	claude plugin validate --strict .

test:
	python3 -m unittest discover -s tests

selftest:
	bash scripts/selftest.sh
	bash scripts/leakscan.sh --selftest

leakscan:
	bash scripts/leakscan.sh

release:
	sh scripts/release-check.sh
