from typing import List
from .base import Rule

from .structure_rules import RequiredChaptersRule
from .structure_quality_rules import ChapterOrderPlausibleRule, ChapterLengthBalancedRule
from .heading_rules import HeadingHierarchyRule, HeadingDepthRule
from .method_results_rules import MethodChapterExistsRule, MethodDetailSufficientRule, ResultsDiscussionSeparationRule
from .figures_tables_rules import FiguresTablesReferencedRule

from .research_question_rules import (
    ResearchQuestionExistsRule,
    ResearchQuestionInIntroRule,
    ResearchKeyTermsConsistencyRule,
    ResearchQuestionReferencedInResultsRule,
    ResearchQuestionReferencedInDiscussionRule,
)
from .literature_rules import (
    LiteratureExistsRule,
    AllCitationsInReferenceListRule,
    NoUncitedReferencesRule,
    CitationStyleConsistentRule,
)
from .literature_quality_rules import CitationDensityRule, ReferenceYearsRule
from .terminology_rules import AbbreviationsListExistsRule, DefinitionsPresentRule
from .structure_extra_rules import ConclusionChapterExistsRule, AbstractExistsRule, IntroHasStructureOverviewRule
from .caption_rules import CaptionsPresentRule
from .toc_lists_rules import TableOfContentsExistsRule, ListOfFiguresExistsRule, ListOfTablesExistsRule
from .numbering_rules import HeadingsMustBeNumberedRule, HeadingNumberingNoGapsRule




def get_all_rules() -> List[Rule]:
    return [
        RequiredChaptersRule(),
        TableOfContentsExistsRule(),          # STRUCT-015

        HeadingHierarchyRule(),
        HeadingDepthRule(),

        HeadingsMustBeNumberedRule(),         # FORM-041a
        HeadingNumberingNoGapsRule(),         # FORM-041b

        ResearchQuestionExistsRule(),
        ResearchQuestionInIntroRule(),
        ResearchKeyTermsConsistencyRule(),
        ResearchQuestionReferencedInResultsRule(),
        ResearchQuestionReferencedInDiscussionRule(),

        ChapterOrderPlausibleRule(),
        ChapterLengthBalancedRule(),

        MethodChapterExistsRule(),
        MethodDetailSufficientRule(),
        ResultsDiscussionSeparationRule(),

        LiteratureExistsRule(),
        AllCitationsInReferenceListRule(),
        NoUncitedReferencesRule(),
        CitationStyleConsistentRule(),

        ListOfFiguresExistsRule(),            # FORM-039 (pflicht wenn Abbildungen)
        ListOfTablesExistsRule(),             # FORM-040 (pflicht wenn Tabellen)

        FiguresTablesReferencedRule(),
    ]

