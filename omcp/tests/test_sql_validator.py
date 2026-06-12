import pytest
from omcp.sql_validator import SQLValidator
import omcp.exceptions as ex


@pytest.fixture
def validator():
    """Create a default SQL validator for testing"""
    return SQLValidator()


@pytest.fixture
def validator_with_source_values():
    """Create a SQL validator that allows source value columns"""
    return SQLValidator(allow_source_value_columns=True)


@pytest.fixture
def validator_with_table_exclusions():
    """Create a SQL validator with exclusions"""
    return SQLValidator(
        exclude_tables=["person", "observation"],
    )


@pytest.fixture
def validator_with_column_exclusions():
    """Create a SQL validator with column exclusions"""
    return SQLValidator(exclude_columns=["ethnicity_concept_id"])


@pytest.fixture
def validator_with_table_and_column_exclusions():
    """Create a SQL validator with table and column exclusions"""
    return SQLValidator(
        exclude_tables=["person", "observation"],
        exclude_columns=["ethnicity_concept_id"],
    )


class TestSQLValidator:
    def test_validate_select_statement(self, validator):
        """Test that a valid SELECT statement passes validation"""
        sql = "SELECT gender_concept_id, race_concept_id FROM person WHERE year_of_birth > 1970"
        errors = validator.validate_sql(sql)
        assert len(errors) == 0, f"Expected no errors, got: {errors}"

    def test_non_select_statement(self, validator):
        """Test that non-SELECT statements are rejected"""
        sql = "INSERT INTO person (person_id) VALUES (1)"
        errors = validator.validate_sql(sql)
        assert len(errors) == 1, f"Expected 1 error, got: {errors}"
        assert isinstance(errors[0], ex.NotSelectQueryError)

    def test_non_omop_table(self, validator):
        """Test that non-OMOP tables are rejected"""
        sql = "SELECT id FROM users"
        errors = validator.validate_sql(sql)
        assert len(errors) == 1
        assert isinstance(errors[0], ex.TableNotFoundError)

    def test_unauthorized_table(self, validator_with_table_exclusions):
        """Test that excluded tables are rejected"""
        sql = "SELECT gender_concept_id FROM person"
        errors = validator_with_table_exclusions.validate_sql(sql)
        assert len(errors) == 1
        assert isinstance(errors[0], ex.UnauthorizedTableError)

    def test_unauthorized_column(self, validator_with_column_exclusions):
        """Test that excluded columns are rejected"""
        sql = "SELECT ethnicity_concept_id FROM person"
        errors = validator_with_column_exclusions.validate_sql(sql)
        assert len(errors) == 1
        assert isinstance(errors[0], ex.UnauthorizedColumnError)

    def test_unauthorized_table_and_column(
        self, validator_with_table_and_column_exclusions
    ):
        """Test that both excluded tables and columns are rejected"""
        sql = "SELECT ethnicity_concept_id FROM person"
        errors = validator_with_table_and_column_exclusions.validate_sql(sql)
        assert len(errors) == 2
        error_types = [type(e) for e in errors]
        assert ex.UnauthorizedTableError in error_types
        assert ex.UnauthorizedColumnError in error_types

    def test_source_value_columns_not_allowed(self, validator):
        """Test that source value columns are rejected by default"""
        sql = "SELECT gender_concept_id, gender_source_value FROM person"
        errors = validator.validate_sql(sql)
        assert len(errors) == 1
        assert isinstance(errors[0], ex.UnauthorizedColumnError)
        assert "Source value columns are not allowed" in str(errors[0])

    def test_source_value_columns_allowed(self, validator_with_source_values):
        """Test that source value columns are allowed when configured"""
        sql = "SELECT gender_concept_id, gender_source_value FROM person"
        errors = validator_with_source_values.validate_sql(sql)
        assert len(errors) == 0, f"Expected no errors, got: {errors}"

    def test_complex_query_validation(self, validator):
        """Test validation of a more complex query with joins"""
        sql = """
        SELECT p.gender_concept_id, c.concept_name
        FROM person p
        JOIN concept c ON p.gender_concept_id = c.concept_id
        WHERE p.year_of_birth > 1970
        """
        errors = validator.validate_sql(sql)
        assert len(errors) == 0, f"Expected no errors, got: {errors}"

    def test_source_concept_id_columns(self, validator):
        """Test that source_concept_id columns are rejected by default"""
        sql = "SELECT gender_concept_id, gender_source_concept_id FROM person"
        errors = validator.validate_sql(sql)
        assert len(errors) == 1
        assert isinstance(errors[0], ex.UnauthorizedColumnError)
        assert "Source value columns are not allowed" in str(errors[0])

    def test_check_is_omop_table_ignores_cte(self, validator):
        """Test that _check_is_omop_table ignores CTEs"""
        sql = """
        WITH patient AS (
            SELECT person_id, gender_concept_id FROM person
        ),
        visits AS (
            SELECT visit_occurrence_id, person_id FROM visit_occurrence
        )
        SELECT p.gender_concept_id, v.visit_occurrence_id
        FROM patient p
        JOIN visits v ON p.person_id = v.person_id
        """
        errors = validator.validate_sql(sql)
        assert len(errors) == 0, f"Expected no errors, got: {errors}"

    def test_check_is_omop_table_ignores_multiple_ctes(self, validator):
        """Test that _check_is_omop_table ignores multiple CTEs with non-OMOP tables"""
        sql = """
        WITH temp_users AS (
            SELECT person_id, gender_concept_id
            FROM person
        ),
        temp_visits AS (
            SELECT visit_occurrence_id, person_id, visit_start_date
            FROM visit_occurrence
        )
        SELECT p.gender_concept_id, v.visit_start_date
        FROM temp_users p
        JOIN temp_visits v ON p.person_id = v.person_id
        """

        errors = validator.validate_sql(sql)
        assert len(errors) == 0, f"Expected no errors, got: {errors}"

    def test_cohort_table_is_valid_omop_table(self, validator):
        """Test that the cohort table is recognized as a valid OMOP table"""
        sql = "SELECT COUNT(*) FROM cohort WHERE cohort_definition_id = 1"
        errors = validator.validate_sql(sql)
        assert len(errors) == 0, f"Expected no errors, got: {errors}"


class TestPIIProjectionCheck:
    """Tests for the PII column projection guard."""

    def test_pii_column_in_projection_blocked(self, validator):
        """Test that PII columns in SELECT projections are rejected"""
        sql = "SELECT subject_id FROM cohort"
        errors = validator.validate_sql(sql)
        assert len(errors) == 1
        assert isinstance(errors[0], ex.UnauthorizedColumnError)
        assert "PII columns cannot be selected directly" in str(errors[0])

    def test_person_id_in_projection_blocked(self, validator):
        """Test that person_id in SELECT projection is rejected"""
        sql = "SELECT person_id FROM person LIMIT 5"
        errors = validator.validate_sql(sql)
        assert len(errors) == 1
        assert isinstance(errors[0], ex.UnauthorizedColumnError)
        assert "person_id" in str(errors[0])

    def test_birth_columns_in_projection_blocked(self, validator):
        """Test that birth date columns in SELECT projection are rejected"""
        sql = "SELECT year_of_birth, month_of_birth FROM person"
        errors = validator.validate_sql(sql)
        assert len(errors) == 1
        assert isinstance(errors[0], ex.UnauthorizedColumnError)
        assert "year_of_birth" in str(errors[0])

    def test_select_star_blocked(self, validator):
        """Test that SELECT * is rejected due to PII exposure"""
        sql = "SELECT * FROM cohort LIMIT 5"
        errors = validator.validate_sql(sql)
        pii_errors = [e for e in errors if "PII" in str(e)]
        assert len(pii_errors) >= 1
        assert "SELECT * is not allowed" in str(pii_errors[0])

    def test_table_star_blocked(self, validator):
        """Test that table.* is rejected due to PII exposure"""
        sql = "SELECT c.* FROM cohort c"
        errors = validator.validate_sql(sql)
        pii_errors = [e for e in errors if "PII" in str(e)]
        assert len(pii_errors) >= 1

    def test_pii_in_aggregate_allowed(self, validator):
        """Test that PII columns inside aggregates are allowed"""
        sql = "SELECT COUNT(DISTINCT subject_id) FROM cohort WHERE cohort_definition_id = 1"
        errors = validator.validate_sql(sql)
        assert len(errors) == 0, f"Expected no errors, got: {errors}"

    def test_count_star_allowed(self, validator):
        """Test that COUNT(*) is allowed (not a bare star)"""
        sql = "SELECT COUNT(*) FROM cohort WHERE cohort_definition_id = 1"
        errors = validator.validate_sql(sql)
        assert len(errors) == 0, f"Expected no errors, got: {errors}"

    def test_pii_in_where_allowed(self, validator):
        """Test that PII columns in WHERE clause are allowed"""
        sql = "SELECT cohort_definition_id FROM cohort WHERE subject_id = 12345"
        errors = validator.validate_sql(sql)
        assert len(errors) == 0, f"Expected no errors, got: {errors}"

    def test_pii_in_join_allowed(self, validator):
        """Test that PII columns in JOIN conditions are allowed"""
        sql = """
        SELECT gender_concept_id, COUNT(*)
        FROM person p
        JOIN cohort c ON c.subject_id = p.person_id
        WHERE c.cohort_definition_id = 1
        GROUP BY 1
        """
        errors = validator.validate_sql(sql)
        assert len(errors) == 0, f"Expected no errors, got: {errors}"

    def test_pii_in_group_by_allowed(self, validator):
        """Test that PII columns in GROUP BY but not projection are allowed"""
        sql = """
        SELECT COUNT(*)
        FROM cohort
        GROUP BY subject_id
        """
        errors = validator.validate_sql(sql)
        assert len(errors) == 0, f"Expected no errors, got: {errors}"

    def test_mixed_pii_and_safe_columns(self, validator):
        """Test that PII column mixed with safe columns is still blocked"""
        sql = "SELECT subject_id, cohort_definition_id FROM cohort"
        errors = validator.validate_sql(sql)
        assert len(errors) == 1
        assert isinstance(errors[0], ex.UnauthorizedColumnError)

    def test_aliased_pii_column_blocked(self, validator):
        """Test that aliased PII columns are still caught"""
        sql = "SELECT subject_id AS sid FROM cohort"
        errors = validator.validate_sql(sql)
        assert len(errors) == 1
        assert isinstance(errors[0], ex.UnauthorizedColumnError)

    def test_cohort_aggregate_demographics(self, validator):
        """Test a realistic cohort demographics query that should pass"""
        sql = """
        SELECT gender_concept_id, COUNT(*) AS cnt
        FROM person p
        JOIN cohort c ON c.subject_id = p.person_id
        WHERE c.cohort_definition_id = 1
        GROUP BY gender_concept_id
        """
        errors = validator.validate_sql(sql)
        assert len(errors) == 0, f"Expected no errors, got: {errors}"

    def test_cohort_count_distinct_subjects(self, validator):
        """Test COUNT(DISTINCT subject_id) query that should pass"""
        sql = "SELECT cohort_definition_id, COUNT(DISTINCT subject_id) FROM cohort GROUP BY 1"
        errors = validator.validate_sql(sql)
        assert len(errors) == 0, f"Expected no errors, got: {errors}"
