#!/usr/bin/python
import luigi
import sciluigi as sl
from lib.tasks import LoadManifest, LoadSpecimenReads, BCCSpecimenReads
from lib.tasks import DADA2_FilterAndTrim, DADA2_Dereplicate


from collections import defaultdict
import logging
import os

ENGINE = 'docker'
log = logging.getLogger('sciluigi-interface')

# Workflow
class Workflow_DADA2(sl.WorkflowTask):
    #
    #  Take a suitable reference package and a set of sequence variants
    #  Place onto the maximum likelihood tree and return a jplace-format
    #  along with some QC data.
    #  For now based on PPLACER, but with an option for others in the future
    #
    working_dir = sl.Parameter()
    destination_dir = sl.Parameter()
    manifest = sl.Parameter()
    barcodecop = sl.Parameter(default=True)

    test_containerinfo = sl.ContainerInfo(
                vcpu=2,
                mem=4096,
                container_cache=os.path.abspath(os.path.join('../working', 'containers/')),
                engine=ENGINE,
                aws_s3_scratch_loc='s3://fh-pi-fredricks-d/lab/golob/sl_temp/',
                aws_jobRoleArn='arn:aws:iam::064561331775:role/fh-pi-fredricks-d-batchtask',
                aws_batch_job_queue='optimal',
                slurm_partition='boneyard'
            )

    def workflow(self):
        #
        #  Load the manifest of files
        #
        manifest = self.new_task(
            'load_manifest',
            LoadManifest,
            path=self.manifest,
        )

        # For each specimen....
        specimen_tasks = defaultdict(dict)
        for specimen in manifest.get_specimens():
            # Load the specimen reads. 
            specimen_tasks[specimen]['reads'] = self.new_task(
                'specimen_load_{}'.format(specimen),
                LoadSpecimenReads,
                specimen=specimen
            )
            specimen_tasks[specimen]['reads'].in_manifest = manifest.out_file
            if self.barcodecop and manifest.has_index() and manifest.is_paired():
                specimen_tasks[specimen]['verified_reads'] = self.new_task(
                    'specimen_bcc_{}'.format(specimen),
                    BCCSpecimenReads,
                    containerinfo=self.test_containerinfo,
                    specimen=specimen,
                    path=os.path.join(
                        self.working_dir,
                        'sv',
                        'bcc'
                    )
                )
                specimen_tasks[specimen]['verified_reads'].in_reads = specimen_tasks[specimen]['reads'].out_reads
            else:
                specimen_tasks[specimen]['verified_reads'] = specimen_tasks[specimen]['reads']

            # DADA2 filer and trim
            specimen_tasks[specimen]['dada2_ft'] = self.new_task(
                'dada2_ft_{}'.format(specimen),
                DADA2_FilterAndTrim,
                containerinfo=self.test_containerinfo,
                specimen=specimen,
                path=os.path.join(
                    self.working_dir,
                    'sv',
                    'dada2',
                    'ft'
                )
            )
            specimen_tasks[specimen]['dada2_ft'].in_reads = specimen_tasks[specimen]['verified_reads'].out_reads

            specimen_tasks[specimen]['dada2_derep'] = self.new_task(
                'dada2_derep_{}'.format(specimen),
                DADA2_Dereplicate,
                containerinfo=self.test_containerinfo,
                specimen=specimen,
                path=os.path.join(
                    self.working_dir,
                    'sv',
                    'dada2',
                    'derep'
                )
            )
            specimen_tasks[specimen]['dada2_derep'].in_reads = specimen_tasks[specimen]['dada2_ft'].out_reads
            

        return (manifest, specimen_tasks)


def build_args(parser):
    parser.add_argument(
        '--working-dir',
        help="""Path of a suitable working directory
        (defaults to the current working directory)""",
        type=str,
        default='.',
    )
    parser.add_argument(
        '--destination-dir',
        help="""Path of a suitable destination directory
        for the various placement outputs""",
        type=str,
        required=True,
    )
    parser.add_argument(
        '-M', '--manifest',
        help="""Manifest of files in CSV format
        one row per specimen. Must at least have columns labeled specimen and read__1
        """,
        type=str,
        required=True,
    )

