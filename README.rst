=================================================
Refatoração do Mezzanine com Padrões de Projeto
=================================================

Trabalho 1 da disciplina **QXD0068 – Reuso de Software** da Universidade
Federal do Ceará, Campus Quixadá, ministrada pelo Prof. Francisco Victor
da Silva Pinheiro: *Refatoração com Padrões de Projeto em Sistema
Legado*.

Integrantes
===========

* Emilly Paiva Belo – Matrícula 563639
* Natan de Sousa Lucena – Matrícula 563641

Descrição do trabalho
=====================

O sistema legado escolhido é o `Mezzanine`_, um CMS de código aberto
escrito em Python sobre o framework Django. O trabalho identificou
problemas de projeto no código original e aplicou quatro padrões GoF
para resolvê-los, preservando o comportamento do sistema:

* **Template Method** em ``mezzanine/generic/fields.py``
  (``BaseGenericRelation`` e subclasses) – PR #1;
* **Strategy** em ``mezzanine/twitter/models.py`` (``Query.run()``) e
  no novo ``mezzanine/twitter/strategies.py`` – PR #2;
* **Factory Method** em ``mezzanine/forms/forms.py``
  (``FormForForm.__init__``) e no novo
  ``mezzanine/forms/field_factories.py`` – PR #4;
* **Facade** em ``mezzanine/forms/page_processors.py``
  (``form_processor``) e no novo ``mezzanine/forms/services.py`` – PR #5.

A PR #3 corrige uma incompatibilidade com o Django 5 que a refatoração
do app twitter tornou visível. Cada refatoração foi feita numa branch e
num pull request próprios, com os testes de caracterização commitados
antes da mudança.

Versões
=======

* ``v-original`` – Mezzanine sem alterações (commit 85dfd412).
* ``v-refatorado`` – versão refatorada (commit ae865f1f, branch
  ``master``).

Resultados
==========

* Suíte de testes: de 86 para 122 testes passando (4 pulados nas duas
  versões, por dependerem do modeltranslation).
* Complexidade ciclomática média dos arquivos envolvidos: de 5,97 (B)
  para 3,23 (A).
* Integração contínua verde em 34 combinações de Python 3.8 a 3.14 e
  Django 2.2 a 5.2, além do lint (isort, black e flake8).

Como executar
=============

Requisitos: Python 3.8 ou superior e Git. No Windows::

    git clone https://github.com/Natan-Lucena/atividade-reuso.git
    cd atividade-reuso
    python -m venv .venv
    .venv\Scripts\python -m pip install -e ".[testing]" "Django>=4.2,<4.3"
    .venv\Scripts\python -m pytest -q --no-cov

No Linux ou macOS, troque ``.venv\Scripts\python`` por
``.venv/bin/python``. O resultado esperado na versão refatorada é
``122 passed, 4 skipped``.

Para executar a versão original, rode ``git checkout v-original`` antes
da instalação (resultado esperado: ``86 passed, 4 skipped``).

Sobre o Mezzanine
=================

O Mezzanine foi criado por Stephen McDonald e é mantido pela comunidade
sob licença BSD. O código original, a documentação e o README original
estão em https://github.com/stephenmcd/mezzanine.

.. _`Mezzanine`: http://mezzanine.jupo.org/
